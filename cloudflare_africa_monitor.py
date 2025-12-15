import requests
import os
import sys
import json
from datetime import datetime, timezone

# --- Configuration ---
CLOUDFLARE_API_URL = "https://www.cloudflarestatus.com/api/v2/components.json"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
STATE_FILE = "cloudflare_state.json"

STATUS_MAPPING = {
    "operational": "Operational",
    "partial_outage": "Partial Outage",
    "under_maintenance": "Under Maintenance",
    "degraded_performance": "Degraded Performance",
    "major_outage": "Major Outage",
}

# Only these Cloudflare *global* components are monitored
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
            with open(STATE_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_current_state(state):
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
    except Exception as e:
        print(f"⚠️ Warning: Could not save state file: {e}")


def send_global_slack_alert(new_issues, new_maintenance, resolved):
    """
    Send ONE message summarizing ONLY the global component CHANGES since last check.
    Tag <!channel> ONLY if a *new* non-operational global issue appeared this check.
    """

    if not SLACK_WEBHOOK_URL:
        return

    # Tag only when NEW issues appear (not on resolve-only runs)
    mention = "<!channel> " if (new_issues or new_maintenance) else ""

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "🌍 Cloudflare Global Status Update", "emoji": True},
        },
        {"type": "divider"},
    ]

    if new_issues:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*🔴 New Global Issues*"}})
        body = ""
        for item in new_issues:
            code = item["code"]
            label = STATUS_MAPPING.get(code, code)
            body += f"• {item['name']} _({label}, code: {code})_\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})
        blocks.append({"type": "divider"})

    if new_maintenance:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*⚠️ New Global Maintenance*"}})
        body = ""
        for item in new_maintenance:
            code = item["code"]
            label = STATUS_MAPPING.get(code, code)
            body += f"• {item['name']} _({label}, code: {code})_\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})
        blocks.append({"type": "divider"})

    if resolved:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*✅ Resolved*"}})
        body = ""
        for item in resolved:
            body += f"• {item['name']}\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"🕒 {datetime.now(timezone.utc).strftime('%H:%M UTC')} | <https://www.cloudflarestatus.com/|Status Page>",
                }
            ],
        }
    )

    payload = {"text": f"{mention}Cloudflare Global Status Update", "blocks": blocks}

    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        print("   -> Global Slack alert sent.")
    except Exception as e:
        print(f"   -> Error sending Slack: {e}")


def main():
    print(f"Starting check at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}...")

    previous_state = load_previous_state()
    current_state = {}

    new_issues = []
    new_maintenance = []
    resolved = []

    try:
        response = requests.get(CLOUDFLARE_API_URL, timeout=20)
        response.raise_for_status()
        data = response.json()
        components = data.get("components", [])

        # Monitor ONLY global components
        monitored = [c for c in components if c.get("name") in GLOBAL_COMPONENTS]
        if not monitored:
            print("⚠️ Warning: No components matched GLOBAL_COMPONENTS list.")

        for comp in monitored:
            name = comp["name"]
            raw_status = comp["status"]
            current_state[name] = raw_status

            last_status = previous_state.get(name, "operational")

            # Only alert on CHANGES (prevents duplicate Slack messages every 5 min)
            if raw_status != last_status:
                if raw_status != "operational":
                    print(f"🔴 CHANGE: {name} -> {raw_status}")
                    item = {"name": name, "code": raw_status}

                    if raw_status == "under_maintenance":
                        new_maintenance.append(item)
                    else:
                        new_issues.append(item)

                elif raw_status == "operational" and last_status != "operational":
                    print(f"✅ RESOLVED: {name} (was {last_status})")
                    resolved.append({"name": name})

            else:
                if raw_status != "operational":
                    print(f"⚠️ Still {raw_status}: {name} (no alert)")

        # Send ONE message if something changed
        if new_issues or new_maintenance or resolved:
            send_global_slack_alert(new_issues, new_maintenance, resolved)
        else:
            print("No global status changes detected.")

        # Persist state so next run doesn't duplicate alerts
        save_current_state(current_state)
        print("Done. State saved.")

    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
