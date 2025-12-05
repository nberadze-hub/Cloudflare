import requests
import os
import sys
import json
from datetime import datetime, timezone

# --- Configuration ---
CLOUDFLARE_API_URL = "https://www.cloudflarestatus.com/api/v2/components.json"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
STATE_FILE = "cloudflare_state.json"

# Optional label mapping (used only for human-friendly Slack output)
STATUS_MAPPING = {
    "operational": "Operational",
    "partial_outage": "Re-routed",
    "under_maintenance": "Partially Re-routed",
    "degraded_performance": "Degraded Performance",
    "major_outage": "Major Outage"
}

# Region groups (PoP regions) to monitor
REGION_GROUPS = ["Africa", "Asia", "Europe", "Latin America & the Caribbean"]

# Global service components to monitor (non-region issues)
# You can tweak this list if Cloudflare renames or adds components.
GLOBAL_COMPONENTS = [
    "Cloudflare Dashboard and APIs",
    "Cloudflare APIs",
    "Cloudflare Dashboard",
    "DNS & Network services",
    "DNS & Network Services",
    "Cloudflare Network",
    "CDN / Edge Network",
]


def load_previous_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_current_state(state):
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        print(f"⚠️ Warning: Could not save state file: {e}")


def send_grouped_slack_alert(outages, maintenance, resolved):
    """
    Sends ONE consolidated message with all updates grouped together,
    divided per region (Africa, Asia, Europe, Latin America & the Caribbean)
    plus a "Global Services" group for global issues.
    """
    if not SLACK_WEBHOOK_URL:
        return

    blocks = []

    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "🌍 Cloudflare Status Update",
            "emoji": True
        }
    })
    blocks.append({"type": "divider"})

    # Determine which groups are present in changes
    all_items = outages + maintenance + resolved
    groups = []
    for item in all_items:
        g = item.get("group", "Unknown")
        if g not in groups:
            groups.append(g)

    # For each region/global group, print its own sections
    for group in groups:
        group_outages = [i for i in outages if i.get("group") == group]
        group_maintenance = [i for i in maintenance if i.get("group") == group]
        group_resolved = [i for i in resolved if i.get("group") == group]

        # Skip groups with no actual changes (just in case)
        if not (group_outages or group_maintenance or group_resolved):
            continue

        # Region/global heading
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*🌍 {group}*"
            }
        })

        # Group 1: Outages (Red)
        if group_outages:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*🔴 Outages (Re-routed)*"}
            })
            text_body = ""
            for item in group_outages:
                code = item["code"]
                label = STATUS_MAPPING.get(code, code)
                text_body += f"• {item['region']} _({label}, code: {code})_\n"

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": text_body}
            })

        # Group 2: Maintenance (Yellow)
        if group_maintenance:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*⚠️ Maintenance (Partially Re-routed)*"}
            })
            text_body = ""
            for item in group_maintenance:
                code = item["code"]
                label = STATUS_MAPPING.get(code, code)
                text_body += f"• {item['region']} _({label}, code: {code})_\n"

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": text_body}
            })

        # Group 3: Resolved (Green)
        if group_resolved:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "*✅ Resolved (Back Online)*"}
            })
            text_body = ""
            for item in group_resolved:
                text_body += f"• {item['region']}\n"

            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": text_body}
            })

        # Divider between regions/groups
        blocks.append({"type": "divider"})

    # Footer (real UTC time now)
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"🕒 {datetime.now(timezone.utc).strftime('%H:%M UTC')} | <https://www.cloudflarestatus.com/|Status Page>"
            }
        ]
    })

    # Payload
    payload = {
        "text": "Cloudflare Status Update",
        "blocks": blocks
    }

    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload)
        print("   -> Grouped Slack alert sent.")
    except Exception as e:
        print(f"   -> Error sending Slack: {e}")


def main():
    print(f"Starting Monitor at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}...")

    previous_state = load_previous_state()
    current_state = {}

    # Lists to collect issues
    new_outages = []
    new_maintenance = []
    new_resolved = []

    try:
        response = requests.get(CLOUDFLARE_API_URL)
        response.raise_for_status()
        data = response.json()

        components = data.get("components", [])

        monitored_regions = []
        region_group_map = {}

        # --- Collect regions from multiple groups ---
        for group_name in REGION_GROUPS:
            group = next(
                (c for c in components if c["name"] == group_name and c.get("group") is True),
                None
            )

            if not group:
                print(f"❌ Error: Could not find '{group_name}' group.")
                continue

            group_id = group["id"]
            group_regions = [c for c in components if c.get("group_id") == group_id]
            print(f"Scanning {len(group_regions)} regions in {group_name}...")
            monitored_regions.extend(group_regions)
            for r in group_regions:
                region_group_map[r["name"]] = group_name

        if not monitored_regions:
            print("❌ Error: Could not find any configured region groups (Africa/Asia/Europe/LATAM).")

        # --- Process region statuses ---
        for region in monitored_regions:
            name = region["name"]
            raw_status = region["status"]
            current_state[name] = raw_status

            last_status = previous_state.get(name, "operational")
            group_name = region_group_map.get(name, "Unknown")

            if raw_status != last_status:

                # Case 1: Something is wrong
                if raw_status != "operational":
                    print(f"🔴 CHANGE: {name} ({group_name}) is {raw_status}")
                    item = {"region": name, "code": raw_status, "group": group_name}

                    if raw_status == "under_maintenance":
                        new_maintenance.append(item)
                    else:
                        new_outages.append(item)

                # Case 2: Something got fixed
                elif raw_status == "operational" and last_status != "operational":
                    print(f"✅ RESOLVED: {name} ({group_name})")
                    new_resolved.append({"region": name, "group": group_name})

            else:
                if raw_status != "operational":
                    print(f"⚠️  {name} ({group_name}) | Still {raw_status} (No alert)")

        # --- Scan global service components ---
        print("\nScanning global Cloudflare service components...")
        monitored_globals = []

        for comp in components:
            if comp["name"] in GLOBAL_COMPONENTS:
                monitored_globals.append(comp)

        for global_comp in monitored_globals:
            name = global_comp["name"]
            raw_status = global_comp["status"]
            current_state[name] = raw_status

            last_status = previous_state.get(name, "operational")
            group_name = "Global Services"

            if raw_status != last_status:

                # Global issue appears
                if raw_status != "operational":
                    print(f"🔴 GLOBAL ISSUE: {name} is {raw_status}")
                    item = {"region": name, "code": raw_status, "group": group_name}

                    if raw_status == "under_maintenance":
                        new_maintenance.append(item)
                    else:
                        new_outages.append(item)

                # Global issue resolved
                elif raw_status == "operational" and last_status != "operational":
                    print(f"✅ GLOBAL RESOLVED: {name}")
                    new_resolved.append({"region": name, "group": group_name})

            else:
                if raw_status != "operational":
                    print(f"⚠️ GLOBAL STILL {raw_status} for {name} (No alert)")

        # --- FINAL STEP: Send ONE message if anything happened ---
        if new_outages or new_maintenance or new_resolved:
            send_grouped_slack_alert(new_outages, new_maintenance, new_resolved)
        else:
            print("No status changes detected.")

        save_current_state(current_state)
        print("\nScan complete. State saved.")

    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
