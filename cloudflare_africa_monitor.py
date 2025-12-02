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
    Sends ONE consolidated message with all updates grouped together.
    """
    if not SLACK_WEBHOOK_URL:
        return

    blocks = []
    
    # Header
    blocks.append({
        "type": "header",
        "text": {
            "type": "plain_text",
            "text": "🌍 Cloudflare Africa Status Update",
            "emoji": True
        }
    })
    blocks.append({"type": "divider"})

    # Group 1: Outages (Red)
    if outages:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*🔴 Outages (Re-routed)*"}
        })
        text_body = ""
        for item in outages:
            text_body += f"• {item['region']} _(Code: {item['code']})_\n"
        
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text_body}
        })

    # Group 2: Maintenance (Yellow)
    if maintenance:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*⚠️ Maintenance (Partially Re-routed)*"}
        })
        text_body = ""
        for item in maintenance:
            text_body += f"• {item['region']} _(Code: {item['code']})_\n"
            
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text_body}
        })

    # Group 3: Resolved (Green)
    if resolved:
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": "*✅ Resolved (Back Online)*"}
        })
        text_body = ""
        for item in resolved:
            text_body += f"• {item['region']}\n"
            
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": text_body}
        })

    # Footer
    blocks.append({
        "type": "context",
        "elements": [
            {
                "type": "mrkdwn",
                "text": f"🕒 {datetime.now().strftime('%H:%M UTC')} | <https://www.cloudflarestatus.com/|Status Page>"
            }
        ]
    })

    # Payload
    payload = {
        "text": "Cloudflare Africa Status Update",
        "blocks": blocks
    }

    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload)
        print("   -> Grouped Slack alert sent.")
    except Exception as e:
        print(f"   -> Error sending Slack: {e}")

def main():
    print(f"Starting Monitor at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
    
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
            
            # --- LOGIC: Collect changes into lists instead of sending immediately ---
            if raw_status != last_status:
                
                # Case 1: Something is wrong
                if raw_status != "operational":
                    print(f"🔴 CHANGE: {name} is {raw_status}")
                    item = {"region": name, "code": raw_status}
                    
                    if raw_status == "under_maintenance":
                        new_maintenance.append(item)
                    else:
                        new_outages.append(item)
                
                # Case 2: Something got fixed
                elif raw_status == "operational" and last_status != "operational":
                    print(f"✅ RESOLVED: {name}")
                    new_resolved.append({"region": name})
            
            else:
                if raw_status != "operational":
                    print(f"⚠️  {name} | Still {raw_status} (No alert)")

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
