#!/usr/bin/env python3

"""
Required environment variables:
NOTION_TOKEN
NOTION_DATABASE_ID
"""

import argparse
import os
from datetime import date, timedelta
from dotenv import load_dotenv

from notion_client import Client
from notion_client.helpers import iterate_paginated_api

ALLOWED_TEAMS = {"Software", "Admin", "Controls"}
DISALLOWED_STATUS = {"DONE", "CANCELED"}


def get_title(properties: dict, name: str) -> str:
    values = properties[name]["title"]
    return values[0]["plain_text"].strip() if values else ""


def get_people(properties: dict, name: str) -> list[str]:
    return [
        person["name"]
        for person in properties[name]["people"]
    ]


def get_date(properties: dict, name: str) -> date | None:
    value = properties[name]["date"]

    if value is None:
        return None

    return date.fromisoformat(value["start"])


def get_status(properties: dict, name: str) -> str | None:
    value = properties[name]["status"]

    if value is None:
        return None

    return value["name"]


def get_formula(properties: dict, name: str) -> str | None:
    value = properties[name]["formula"]

    if value is None:
        return None

    return value.get("string")


def get_teams(properties: dict, name: str) -> set[str]:
    return {
        team["name"]
        for team in properties[name]["multi_select"]
    }


def get_url(properties: dict, name: str) -> str | None:
    return properties[name]["url"]


def get_tasks(notion: Client, data_source_id: str) -> list[dict]:
    """Retrieve every task from the Notion data source."""

    tasks = []

    for page in iterate_paginated_api(
        notion.data_sources.query,
        data_source_id=data_source_id,
    ):
        properties = page["properties"]
        
        teams = get_teams(properties, "Team")
        status = get_status(properties, "Status")

        if (not teams & ALLOWED_TEAMS) or (status in DISALLOWED_STATUS):
            continue

        tasks.append({
            "name": get_title(properties, "Name"),
            "owners": get_people(properties, "Owner"),
            "deadline": get_date(properties, "Deadline"),
            "status": get_status(properties, "Status"),
            "pr": get_formula(properties, "PR"),
            "link": get_url(properties, "Link"),
        })

    return tasks


def format_owners(owners: list[str]) -> str:
    return " ".join(f"@{owner}" for owner in owners)


def format_task(task: dict, include_deadline: bool = True) -> list[str]:
    owners = format_owners(task["owners"])
    owner_text = f": {owners}" if owners else ""

    if include_deadline and task["deadline"] is not None:
        deadline_text = f" *({task['deadline'].strftime('%b %-d')})*"
    else:
        deadline_text = ""

    lines = [f"•  {task['name']}{owner_text}{deadline_text}"]

    if task["pr"]:
        if task["link"]:
            lines.append(f"    •  {task['link']}")
        else:
            lines.append(f"    •  {task['pr']}")

    return lines


def generate_slack(tasks: list[dict], today: date | None = None) -> str:
    if today is None:
        today = date.today()

    # Monday = 0 ... Sunday = 6
    sunday = today + timedelta(days=6 - today.weekday())

    due_this_week = []
    upcoming = []
    requiring_owner = []

    for task in tasks:
        has_owner = bool(task["owners"])
        has_deadline = task["deadline"] is not None

        # Specifically:
        # TO DO + no deadline + no owner
        if (
            task["status"] == "TO DO"
            and not has_deadline
            and not has_owner
        ):
            requiring_owner.append(task)
            continue

        # Tasks with deadlines go into the normal sections.
        if has_deadline:
            if task["deadline"] <= sunday:
                due_this_week.append(task)
            else:
                upcoming.append(task)

    # Sort chronologically, then by owner
    due_this_week.sort(
        key=lambda task: (task["deadline"], task["owners"])
    )

    upcoming.sort(
        key=lambda task: (task["deadline"], task["name"].lower())
    )

    requiring_owner.sort(
        key=lambda task: task["name"].lower()
    )

    output = [
        "*Active/Assigned:*",
        "This week",
    ]

    for task in due_this_week:
        output.extend(format_task(task))

    output.extend([
        "",
        "Upcoming:",
    ])

    for task in upcoming:
        output.extend(format_task(task))

    output.extend([
        "",
        "Requiring owner:",
    ])

    for task in requiring_owner:
        output.append(
            f"• {task['name']}: *OWNER REQUIRED*"
        )

        if task["pr"]:
            output.append(
                f"  PR: {task['pr']}"
            )

    return "\n".join(output)


def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Generate a Slack task summary from a Notion Project Board."
    )

    parser.add_argument(
        "--data-source-id",
        default=os.environ.get("NOTION_DATABASE_ID"),
        help="Notion data source ID "
             "(defaults to NOTION_DATABASE_ID environment variable)",
    )

    parser.add_argument(
        "--token",
        default=os.environ.get("NOTION_TOKEN"),
        help="Notion API token "
             "(defaults to NOTION_TOKEN environment variable)",
    )

    args = parser.parse_args()

    if not args.token:
        parser.error(
            "No Notion token supplied. "
            "Set NOTION_TOKEN or use --token."
        )

    if not args.data_source_id:
        parser.error(
            "No data source ID supplied. "
            "Set NOTION_DATABASE_ID or use --data-source-id."
        )

    notion = Client(auth=args.token)

    tasks = get_tasks(
        notion,
        args.data_source_id,
    )

    print(generate_slack(tasks))


if __name__ == "__main__":
    main()