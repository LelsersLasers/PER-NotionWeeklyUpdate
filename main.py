#!/usr/bin/env python3

import re
import sys
from datetime import date, datetime, timedelta


def parse_date(value: str, year: int) -> date:
    """Parse dates like 'Sep 5' using the supplied year."""
    value = re.sub(r"<br\s*/?>", "", value, flags=re.IGNORECASE).strip()

    # Handle dates such as "Sep 5"
    return datetime.strptime(f"{value} {year}", "%b %d %Y").date()


def clean_markdown(value: str) -> str:
    """Remove basic Markdown/HTML formatting from a table cell."""
    value = value.strip()

    # Remove HTML breaks
    value = re.sub(r"<br\s*/?>", "", value, flags=re.IGNORECASE)

    # Convert [text](url) -> text
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)

    return value.strip()


def slack_owner(name: str) -> str:
    """
    Convert an owner string into Slack-friendly @ mentions.

    Example:
        'Amruth Nadimpally, Aditya Saini'
        -> '@Amruth Nadimpally, @Aditya Saini'
    """
    name = clean_markdown(name)

    if not name or name in {"-", "<br>"}:
        return ""

    owners = [owner.strip() for owner in name.split(",") if owner.strip()]

    return ", ".join(f"@{owner}" for owner in owners)


def parse_table(text: str):
    """Parse rows from a Markdown table."""
    tasks = []

    for line in text.splitlines():
        line = line.strip()

        # Only process actual table rows
        if not line.startswith("|"):
            continue

        cells = [cell.strip() for cell in line.strip("|").split("|")]

        # Skip header/separator rows
        if len(cells) < 7:
            continue

        if cells[0].lower() == "name":
            continue

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

    # Sunday of the current week.
    #
    # Python:
    #   Monday = 0
    #   ...
    #   Sunday = 6
    days_until_sunday = 6 - today.weekday()
    next_sunday = today + timedelta(days=days_until_sunday)

    tasks = parse_table(text)

    due_this_week = []
    upcoming = []

    for task in tasks:
        try:
            deadline = parse_date(task["deadline"], year)
        except ValueError:
            print(
                f"Warning: could not parse deadline "
                f"{task['deadline']!r} for {task['name']!r}",
                file=sys.stderr,
            )
            continue

        # If a deadline has already passed this year, don't accidentally
        # classify it as an upcoming task.
        if deadline <= next_sunday:
            due_this_week.append((deadline, task))
        else:
            upcoming.append((deadline, task))

    # Sort chronologically
    due_this_week.sort(key=lambda x: x[0])
    upcoming.sort(key=lambda x: x[0])

    output = []

    output.append("*due this week*")
    output.append("")

    for deadline, task in due_this_week:
        owner = slack_owner(task["owner"])

        owner_text = f": {owner}" if owner else ""

        output.append(
            f"- {task['name']}{owner_text} "
            f"*(Sep {deadline.day})*"
        )

    output.append("")
    output.append("*upcoming*")
    output.append("")

    for deadline, task in upcoming:
        owner = slack_owner(task["owner"])

        owner_text = f": {owner}" if owner else ""

        output.append(
            f"- {task['name']}{owner_text} "
            f"*(Sep {deadline.day})*"
        )

    return "\n".join(output)


if __name__ == "__main__":
    # Usage:
    #
    #   python3 tasks.py < tasks.md
    #
    # or:
    #
    #   python3 tasks.py tasks.md
    #

    if len(sys.argv) > 1:
        with open(sys.argv[1], "r", encoding="utf-8") as f:
            table = f.read()
    else:
        table = sys.stdin.read()

    print(generate_slack(table))
