import os
import sys
import json
from datetime import datetime, timezone

import requests

CLOUDFLARE_API_URL = "https://www.cloudflarestatus.com/api/v2/components.json"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

# Region groups to show in Slack (must match Cloudflare component group names)
REGION_GROUPS = [
    "Africa",
    "Asia",
    "Europe",
    "Latin America & the Caribbean",
]

STATUS_MAPPING = {
    "partial_outage": "Re-routed",
    "under_maintenance": "Partially Re-routed",
}

def fetch_components():
    resp = requests.get(CLOUDFLARE_API_URL, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    return data.get("components", [])


def build_region_lists(components):
    """
    Returns:
    - regions_by_group: { group_name: [region_component_dict, ...] }
    - issues_by_group: {
          group_name: {
              "partial_outage": [region_name, ...],
              "under_maintenance": [region_name, ...],
          }
      }
    """
    regions_by_group = {g: [] for g in REGION_GROUPS}
    issues_by_group = {
        g: {"partial_outage": [], "under_maintenance": []}
        for g in REGION_GROUPS
    }

    # First, map group IDs for the region groups
    group_id_by_name = {}
    for c in components:
        if c.get("group") is True and c["name"] in REGION_GROUPS:
            group_id_by_name[c["name"]] = c["id"]

    # Now gather the regions under those groups
    for c in components:
        group_id = c.get("group_id")
        if not group_id:
            continue

        # Find which group name this belongs to
        group_name = None
        for name, gid in group_id_by_name.items():
            if gid == group_id:
                group_name = name
                break

        if not group_name:
            continue

        regions_by_group[group_name].append(c)

        status = c.get("status")
        if status in ("partial_outage", "under_maintenance"):
            issues_by_group[group_name][status].append(c["name"])

    return regions_by_group, issues_by_group


def build_slack_blocks(issues_by_group):
    blocks = []

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "🌍 Cloudflare Reroute Snapshot",
            "emoji": True,
        },
    })
    blocks.append({"type": "divider"})

    # Check if there are any issues at all
    any_issues = any(
        issues_by_group[g]["partial_outage"] or issues_by_group[g]["under_maintenance"]
        for g in REGION_GROUPS
    )

    if not any_issues:
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "✅ No *Re-routed* or *Partially Re-routed* regions right now.\nAll monitored regions are operational."
            }
