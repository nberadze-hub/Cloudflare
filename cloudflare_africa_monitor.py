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

    if is_resolved:
        color = "#36a64f" # Green
        emoji = "✅"
        title = "Cloudflare Issue Resolved"
        status_msg = "Back Operational"
    else:
        # Yellow for maintenance, Red for outages
        color = "#FFD700" if status_raw == "under_maintenance" else "#FF0000"
        emoji = "⚠️" if status_raw == "under_maintenance" else "🔴"
        title = "Cloudflare Status Alert"
        status_msg = f"{status_friendly}\n_({status_raw})_"

    payload = {
        "text": f"{emoji} {title}: {region_name}",
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {
                        "type": "header",
                        "text": {"type": "plain_text", "text": f"{emoji} {title}", "emoji": True}
                    },
                    {
                        "type": "section",
                        "fields": [
                            {"type": "mrkdwn", "text": f"*Region:*\n{region_name}"},
                            {"type": "mrkdwn", "text": f"*Status:*\n{status_msg}"}
                        ]
                    },
                    {
                        "type": "context",
                        "elements": [{"type": "mrkdwn", "text": f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}"}]
                    }
                ]
            }
        ]
    }

    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload)
        print(f"   -> Slack alert sent for {region_name}")
    except Exception as e:
        print(f"   -> Error sending Slack: {e}")

def main():
    print(f"Starting Monitor at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
    
    # 1. Load memory from last run
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
            
            # Save this status to the "Current" memory for next time
            current_state[name] = raw_status 
            
            # Retrieve what this region was doing 5 minutes ago
            # If we don't have a record (first run), assume it was "operational" so we alert if it's broken now
            last_status = previous_state.get(name, "operational")
            
            friendly_status = STATUS_MAPPING.get(raw_status, raw_status)

            # --- INTELLIGENT ALERT LOGIC ---
            
            # Only alert if the status has CHANGED
            if raw_status != last_status:
                
                # Scenario A: It just broke (or changed from Maint -> Outage)
                if raw_status != "operational":
                    print(f"🔴 CHANGE DETECTED: {name} is now {raw_status}")
                    send_slack_alert(name, friendly_status, raw_status, is_resolved=False)
                
                # Scenario B: It just got fixed (Broken -> Operational)
                elif raw_status == "operational" and last_status != "operational":
                    print(f"✅ RESOLVED: {name} is back online")
                    send_slack_alert(name, friendly_status, raw_status, is_resolved=True)
            
            else:
                # No change? Do nothing (prevent spam)
                if raw_status != "operational":
                    print(f"⚠️  {name} | Still {raw_status} (No alert sent)")
                else:
                    print(f"✅ {name} | Operational")

        # 2. Save memory for next run
        save_current_state(current_state)
        print("\nScan complete. State saved.")

    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
