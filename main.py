#!/usr/bin/env python3

import argparse
import re
from datetime import date, datetime, timedelta


def parse_date(value: str, year: int) -> date:
    value = re.sub(r"<br\s*/?>", "", value, flags=re.IGNORECASE).strip()
    return datetime.strptime(f"{value} {year}", "%b %d %Y").date()


def clean_markdown(value: str) -> str:
    value = value.strip()

    value = re.sub(r"<br\s*/?>", "", value, flags=re.IGNORECASE)
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)

    return value.strip()


def slack_owner(name: str) -> str:
    name = clean_markdown(name)

    if not name or name in {"-", "<br>"}:
        return ""

    owners = [
        owner.strip()
        for owner in name.split(",")
        if owner.strip()
    ]

    return ", ".join(f"@{owner}" for owner in owners)


def parse_table(text: str):
    tasks = []

    for line in text.splitlines():
        line = line.strip()

        if not line.startswith("|"):
            continue

        cells = [
            cell.strip()
            for cell in line.strip("|").split("|")
        ]

        if len(cells) < 7:
            continue

        # Skip header
        if cells[0].lower() == "name":
            continue

        # Skip separator
        if re.fullmatch(r"[-: ]+", cells[0]):
            continue

        name, project, team, status, priority, owner, deadline = cells[:7]

        name = clean_markdown(name)
        owner = clean_markdown(owner)

        if not deadline:
            continue

        tasks.append({
            "name": name,
            "owner": owner,
            "deadline": deadline,
        })

    return tasks


def generate_slack(text: str, today: date | None = None) -> str:
    if today is None:
        today = date.today()

    year = today.year

    # Sunday at the end of the current week.
    days_until_sunday = 6 - today.weekday()
    sunday = today + timedelta(days=days_until_sunday)

    tasks = parse_table(text)

    due_this_week = []
    upcoming = []

    for task in tasks:
        try:
            deadline = parse_date(task["deadline"], year)
        except ValueError:
            print(
                f"Warning: could not parse deadline "
                f"{task['deadline']!r} for {task['name']!r}"
            )
            continue

        if deadline <= sunday:
            due_this_week.append((deadline, task))
        else:
            upcoming.append((deadline, task))

    due_this_week.sort(key=lambda x: x[0])
    upcoming.sort(key=lambda x: x[0])

    output = [
        "*due this week*",
        "",
    ]

    for deadline, task in due_this_week:
        owner = slack_owner(task["owner"])
        owner_text = f": {owner}" if owner else ""

        output.append(
            f"- {task['name']}{owner_text} "
            f"*({deadline.strftime('%b %-d')})*"
        )

    output.extend([
        "",
        "*upcoming*",
        "",
    ])

    for deadline, task in upcoming:
        owner = slack_owner(task["owner"])
        owner_text = f": {owner}" if owner else ""

        output.append(
            f"- {task['name']}{owner_text} "
            f"*({deadline.strftime('%b %-d')})*"
        )

    return "\n".join(output)


def main():
    parser = argparse.ArgumentParser(
        description="Convert a task Markdown table into Slack-formatted deadlines."
    )

    parser.add_argument(
        "csv",
        help="Path to the CSV file containing the tasks",
    )

    args = parser.parse_args()

    with open(args.csv, "r", encoding="utf-8") as f:
        table = f.read()

    print(generate_slack(table))


if __name__ == "__main__":
    main()
