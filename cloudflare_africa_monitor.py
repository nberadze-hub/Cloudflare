import requests
import os
import sys
import json
from datetime import datetime

# --- Configuration ---
CLOUDFLARE_API_URL = "https://www.cloudflarestatus.com/api/v2/components.json"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

STATUS_MAPPING = {
    "operational": "Operational",
    "partial_outage": "Re-routed",
    "under_maintenance": "Partially Re-routed",
    "degraded_performance": "Degraded Performance",
    "major_outage": "Major Outage"
}

def send_slack_alert(region_name, status_friendly, status_raw):
    """
    Sends a formatted alert to Slack.
    """
    if not SLACK_WEBHOOK_URL:
        print("   -> No Slack URL found. Skipping alert.")
        return

    # Color Logic: Yellow for maintenance, Red for everything else
    color = "#FFD700" if status_raw == "under_maintenance" else "#FF0000"
    emoji = "⚠️" if status_raw == "under_maintenance" else "🔴"

    payload = {
        "text": f"{emoji} Issue detected in {region_name}",
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": f"{emoji} Cloudflare Status Alert",
                            "emoji": True
                        }
                    },
                    {
                        "type": "section",
                        "fields": [
                            {
                                "type": "mrkdwn",
                                "text": f"*Region:*\n{region_name}"
                            },
                            {
                                "type": "mrkdwn",
                                "text": f"*Status:*\n{status_friendly}\n_({status_raw})_"
                            }
                        ]
                    },
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"
                            }
                        ]
                    }
                ]
            }
        ]
    }

    try:
        response = requests.post(SLACK_WEBHOOK_URL, json=payload)
        if response.status_code == 200:
            print(f"   -> Slack alert sent for {region_name}")
        else:
            print(f"   -> Failed to send Slack alert: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"   -> Error sending Slack alert: {e}")

def main():
    print(f"Starting Monitor at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
    
    try:
        # 1. Fetch Cloudflare Data
        response = requests.get(CLOUDFLARE_API_URL)
        response.raise_for_status()
        data = response.json()
        
        # 2. Find Africa Group
        components = data.get("components", [])
        africa_group = next((c for c in components if c["name"] == "Africa" and c.get("group") is True), None)
        
        if not africa_group:
            print("❌ Error: Could not find 'Africa' group.")
            return

        africa_group_id = africa_group["id"]
        africa_regions = [c for c in components if c.get("group_id") == africa_group_id]
        
        print(f"Scanning {len(africa_regions)} regions...")
        issues_found = 0
        
        # 3. Check Each Region
        for region in africa_regions:
            name = region["name"]
            raw_status = region["status"]
            
            # Only alert if NOT operational
            if raw_status != "operational":
                issues_found += 1
                friendly_status = STATUS_MAPPING.get(raw_status, raw_status)
                
                print(f"🔴 {name} | {friendly_status} ({raw_status})")
                send_slack_alert(name, friendly_status, raw_status)
            else:
                # Optional: Print healthy regions to log just to show it's working
                print(f"✅ {name} | Operational")

        print(f"\nScan complete. {issues_found} issues detected.")

    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
