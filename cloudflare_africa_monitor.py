import requests
import os
import json
import sys
from datetime import datetime

# --- Configuration ---
CLOUDFLARE_API_URL = "https://www.cloudflarestatus.com/api/v2/components.json"
INCIDENT_IO_WEBHOOK = os.environ.get("INCIDENT_IO_WEBHOOK")
INCIDENT_IO_SECRET = os.environ.get("INCIDENT_IO_SECRET")

# This maps the "Tech Speak" (API) to "Human Speak" (Website)
STATUS_MAPPING = {
    "operational": "Operational",
    "partial_outage": "Re-routed",
    "under_maintenance": "Partially Re-routed",
    "degraded_performance": "Degraded Performance",
    "major_outage": "Major Outage"
}

def get_status_emoji(status):
    # Operational = Green Check
    if status == "operational":
        return "✅"
    # Maintenance = Yellow Warning
    elif status == "under_maintenance":
        return "⚠️"
    # Outages/Degraded/Major = Red Circle
    else:
        return "🔴"

def send_incident_io_alert(region_name, status_display, raw_status):
    """
    Sends an alert to incident.io if a webhook is configured.
    """
    if not INCIDENT_IO_WEBHOOK:
        return

    payload = {
        "title": f"Cloudflare Status Change: {region_name}",
        "description": f"Region: {region_name}\nCurrent Status: {status_display}\nTechnical Code: {raw_status}",
        "status": "firing",
        "deduplication_key": f"cloudflare-{region_name}",
        "metadata": {
            "source": "Cloudflare Monitor",
            "region": region_name,
            "raw_status": raw_status
        }
    }

    headers = {"Content-Type": "application/json"}
    if INCIDENT_IO_SECRET:
        headers["Authorization"] = f"Bearer {INCIDENT_IO_SECRET}"

    try:
        response = requests.post(INCIDENT_IO_WEBHOOK, json=payload, headers=headers)
        if response.status_code in [200, 201, 202]:
            print(f"   -> Alert sent to incident.io for {region_name}")
        else:
            print(f"   -> Failed to send alert: {response.status_code} - {response.text}")
    except Exception as e:
        print(f"   -> Error sending alert: {str(e)}")

def main():
    print(f"Starting Cloudflare Africa Monitor at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}...")
    
    try:
        # 1. Fetch all Cloudflare components
        response = requests.get(CLOUDFLARE_API_URL)
        response.raise_for_status()
        data = response.json()
        
        # 2. Find the 'Africa' group ID
        components = data.get("components", [])
        africa_group = next((c for c in components if c["name"] == "Africa" and c.get("group") is True), None)
        
        if not africa_group:
            print("❌ Error: Could not find 'Africa' group in Cloudflare API.")
            return

        africa_group_id = africa_group["id"]
        print(f"Found Africa Group ID: {africa_group_id}")

        # 3. Filter for components that belong to Africa
        africa_regions = [c for c in components if c.get("group_id") == africa_group_id]
        
        print(f"Monitoring {len(africa_regions)} African regions...\n")
        print("-" * 60)
        print(f"{'REGION':<40} | {'STATUS'}")
        print("-" * 60)

        issues_found = 0

        # 4. Check status for each region
        for region in africa_regions:
            name = region["name"]
            raw_status = region["status"]
            
            # Get the "Website Friendly" name
            friendly_status = STATUS_MAPPING.get(raw_status, raw_status.replace("_", " ").title())
            emoji = get_status_emoji(raw_status)

            # --- THE HYBRID LOGIC ---
            # If it is NOT operational, we show: "Friendly Name (raw_code)"
            if raw_status != "operational":
                display_status = f"{friendly_status} ({raw_status})"
                issues_found += 1
                
                # Print to logs with a warning color/format
                print(f"{emoji} {name:<38} | {display_status}")
                
                # Trigger Alert
                send_incident_io_alert(name, display_status, raw_status)
            else:
                # If operational, just show "Operational" (clean)
                print(f"{emoji} {name:<38} | {friendly_status}")

        print("-" * 60)
        print(f"\nScan complete. {issues_found} issues found.")

    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
