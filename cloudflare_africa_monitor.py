import requests
import os
import sys
import json
from datetime import datetime

# --- Configuration ---
CLOUDFLARE_API_URL = "https://www.cloudflarestatus.com/api/v2/components.json"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")
STATE_FILE = "cloudflare_state.json"

STATUS_MAPPING = {
    "operational": "Operational",
    "partial_outage": "Re-routed",
    "under_maintenance": "Partially Re-routed",
    "degraded_performance": "Degraded Performance",
    "major_outage": "Major Outage"
}

def load_previous_state():
    """Loads the state from the last run (if it exists)."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r') as f:
                return json.load(f)
        except Exception:
            return {}
    return {}

def save_current_state(state):
    """Saves the current state for the next run."""
    try:
        with open(STATE_FILE, 'w') as f:
            json.dump(state, f)
    except Exception as e:
        print(f"⚠️ Warning: Could not save state file: {e}")

def send_slack_alert(region_name, status_friendly, status_raw, is_resolved=False):
    if not SLACK_WEBHOOK_URL:
        return

    # 1. Determine Visuals (Emoji & Header)
    if is_resolved:
        emoji = "✅"
        header_text = "Issue Resolved"
        status_text = f"*Status:* {emoji} Back Operational"
    else:
        # Maintenance = Yellow, Outage = Red
        if status_raw == "under_maintenance":
            emoji = "⚠️"
            header_text = "Maintenance Alert"
        else:
            emoji = "🔴"
            header_text = "Outage Alert"
        
        status_text = f"*Status:* {emoji} {status_friendly}\n_Code: {status_raw}_"

    # 2. Build "Block Kit" Payload (The Modern Design)
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} Cloudflare: {header_text}",
                "emoji": True
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Region:*\n🌍 {region_name}"
                },
                {
                    "type": "mrkdwn",
                    "text": status_text
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"🕒 Detected at {datetime.now().strftime('%H:%M UTC')} | <https://www.cloudflarestatus.com/|View Status Page>"
                }
            ]
        }
    ]

    # The 'text' field is what shows up in the notification popup on your phone/desktop
    notification_text = f"{emoji} {header_text}: {region_name}"

    payload = {
        "text": notification_text,
        "blocks": blocks
    }

    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload)
        print(f"   -> Slack alert sent for {region_name}")
    except Exception as e:
        print(f"   -> Error sending Slack: {e}")

def main():
    print(f"Starting Monitor at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
    
    previous_state = load_previous_state()
    current_state = {}
    
    try:
        response = requests.get(CLOUDFLARE_API_URL)
        response.raise_for_status()
        data = response.json()
        
        components = data.get("components", [])
        africa_group = next((c for c in components if c["name"] == "Africa" and c.get("group") is True), None)
        
        if not africa_group:
            print("❌ Error: Could not find 'Africa' group.")
            return

        africa_group_id = africa_group["id"]
        africa_regions = [c for c in components if c.get("group_id") == africa_group_id]
        
        print(f"Scanning {len(africa_regions)} regions...")
        
        for region in africa_regions:
            name = region["name"]
            raw_status = region["status"]
            current_state[name] = raw_status 
            
            last_status = previous_state.get(name, "operational")
            friendly_status = STATUS_MAPPING.get(raw_status, raw_status)

            if raw_status != last_status:
                if raw_status != "operational":
                    print(f"🔴 CHANGE: {name} is {raw_status}")
                    send_slack_alert(name, friendly_status, raw_status, is_resolved=False)
                elif raw_status == "operational" and last_status != "operational":
                    print(f"✅ RESOLVED: {name} is online")
                    send_slack_alert(name, friendly_status, raw_status, is_resolved=True)
            else:
                if raw_status != "operational":
                    print(f"⚠️  {name} | Still {raw_status} (No alert)")
                else:
                    print(f"✅ {name} | Operational")

        save_current_state(current_state)
        print("\nScan complete. State saved.")

    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
