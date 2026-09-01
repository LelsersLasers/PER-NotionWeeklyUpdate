#!/usr/bin/env python3

import argparse
import csv
import re
import tempfile
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path


def clean_markdown(value: str) -> str:
    """Remove basic Markdown/HTML formatting from a cell."""
    value = value.strip()

    value = re.sub(r"<br\s*/?>", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)

    return value.strip()


def slack_owner(name: str) -> str:
    """Convert comma-separated owner names to @mentions."""
    name = clean_markdown(name)

    if not name or name in {"-", "<br>"}:
        return ""

    owners = [
        owner.strip()
        for owner in name.split(",")
        if owner.strip()
    ]

    return " ".join(f"@{owner}" for owner in owners)


def parse_date(value: str, year: int) -> date:
    """Parse a deadline such as 'Sep 5'."""
    value = clean_markdown(value)
    return datetime.strptime(
        f"{value} {year}",
        "%b %d %Y",
    ).date()


def find_project_board_csv(root: Path) -> Path:
    """
    Find the Project Board CSV we actually care about.

    Notion exports both:
        Project Board <id>.csv
        Project Board <id>_all.csv

    We want the former.
    """
    candidates = []

    for path in root.rglob("*.csv"):
        if path.name.endswith("_all.csv"):
            continue

        if path.name.startswith("Project Board ") and path.name.endswith(".csv"):
            candidates.append(path)

    if not candidates:
        raise FileNotFoundError(
            "Could not find the Project Board CSV in the extracted archive."
        )

    if len(candidates) > 1:
        raise RuntimeError(
            "Found multiple possible Project Board CSV files:\n"
            + "\n".join(f"  {path}" for path in candidates)
        )

    return candidates[0]


def extract_zip(zip_path: Path, destination: Path) -> None:
    """Safely extract a ZIP archive."""
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(destination)


def extract_nested_export(outer_zip: Path, temp_dir: Path) -> Path:
    """
    Extract the Notion export structure:

        outer.zip
          └── inner.zip
                └── Private & Shared/
                      └── Project Board ....csv

    Returns the path to the desired CSV.
    """
    outer_dir = temp_dir / "outer"
    outer_dir.mkdir()

    extract_zip(outer_zip, outer_dir)

    # Find the nested ZIP without assuming its filename.
    nested_zips = list(outer_dir.rglob("*.zip"))

    if not nested_zips:
        raise FileNotFoundError(
            "No nested ZIP archive found inside the outer ZIP."
        )

    if len(nested_zips) > 1:
        raise RuntimeError(
            "Found multiple nested ZIP archives:\n"
            + "\n".join(f"  {path}" for path in nested_zips)
        )

    inner_zip = nested_zips[0]

    inner_dir = temp_dir / "inner"
    inner_dir.mkdir()

    extract_zip(inner_zip, inner_dir)

    return find_project_board_csv(inner_dir)


def parse_tasks(csv_path: Path):
    """Read tasks from the Project Board CSV."""
    tasks = []

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        required_columns = {
            "Name",
            "Deadline",
            "Owner",
        }

        if not required_columns.issubset(reader.fieldnames or set()):
            raise ValueError(
                "CSV is missing required columns. "
                f"Expected at least: {', '.join(sorted(required_columns))}\n"
                f"Found: {', '.join(reader.fieldnames or [])}"
            )

        for row in reader:
            name = clean_markdown(row["Name"])
            owner = clean_markdown(row["Owner"])
            deadline = clean_markdown(row["Deadline"])

            if not name:
                continue

            tasks.append({
                "name": name,
                "owner": owner,
                "deadline": deadline,
            })

    return tasks


def generate_slack(tasks, today: date | None = None) -> str:
    """Generate the Slack-formatted task list."""
    if today is None:
        today = date.today()

    # Monday = 0 ... Sunday = 6
    days_until_sunday = 6 - today.weekday()
    sunday = today + timedelta(days=days_until_sunday)

    due_this_week = []
    upcoming = []
    requiring_owner = []

    for task in tasks:
        owner = clean_markdown(task["owner"])
        deadline_value = clean_markdown(task["deadline"])

        # No owner -> put it in its own section regardless of deadline.
        if not owner or owner in {"-", "<br>"}:
            requiring_owner.append(task)
            continue

        # No deadline, but has an owner -> don't put it into either
        # date-based section.
        if not deadline_value:
            continue

        try:
            deadline = parse_date(deadline_value, today.year)
        except ValueError:
            print(
                f"Warning: could not parse deadline "
                f"{deadline_value!r} for {task['name']!r}"
            )
            continue

        if deadline <= sunday:
            due_this_week.append((deadline, task))
        else:
            upcoming.append((deadline, task))

    due_this_week.sort(key=lambda item: item[0])
    upcoming.sort(key=lambda item: item[0])
    requiring_owner.sort(key=lambda task: task["name"].lower())

    output = [
        "*Active/Assigned:*",
        "This week",
    ]

    for deadline, task in due_this_week:
        owner = slack_owner(task["owner"])

        output.append(
            f"• {task['name']}: {owner} "
            f"*({deadline.strftime('%b %-d')})*"
        )

    output.extend([
        "",
        "Upcoming:",
    ])

    for deadline, task in upcoming:
        owner = slack_owner(task["owner"])

        output.append(
            f"• {task['name']}: {owner} "
            f"*({deadline.strftime('%b %-d')})*"
        )

    output.extend([
        "",
        "Requiring owner:",
    ])

    for task in requiring_owner:
        output.append(
            f"• {task['name']}: *OWNER REQUIRED*"
        )

    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Extract a Notion Project Board export and generate "
            "a Slack-formatted task list."
        )
    )

    parser.add_argument(
        "zip",
        type=Path,
        help="Path to the outer Notion export ZIP",
    )

    args = parser.parse_args()

    if not args.zip.is_file():
        parser.error(f"ZIP file does not exist: {args.zip}")

    if not zipfile.is_zipfile(args.zip):
        parser.error(f"File is not a valid ZIP archive: {args.zip}")

    # Everything created during extraction lives inside this directory.
    # It is automatically deleted when the block exits, including when
    # an exception is raised.
    with tempfile.TemporaryDirectory(prefix="project-board-") as temp:
        temp_dir = Path(temp)

        csv_path = extract_nested_export(
            args.zip,
            temp_dir,
        )

        tasks = parse_tasks(csv_path)

        print(generate_slack(tasks))


if __name__ == "__main__":
    main()
