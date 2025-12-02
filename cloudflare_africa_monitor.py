#!/usr/bin/env python3
"""
Cloudflare Africa Region Monitor
Monitors Cloudflare status page for African regions and alerts to incident.io
"""

import os
import json
import hashlib
import requests
from datetime import datetime
from typing import Dict, List, Optional

# Configuration
CLOUDFLARE_STATUS_API = "https://www.cloudflarestatus.com/api/v2/components.json"
INCIDENT_IO_WEBHOOK = os.environ.get("INCIDENT_IO_WEBHOOK", "")
INCIDENT_IO_SECRET = os.environ.get("INCIDENT_IO_SECRET", "")
STATE_FILE = "/tmp/cloudflare_state.json"


def get_cloudflare_status() -> List[Dict]:
    """Fetch current status from Cloudflare API"""
    try:
        response = requests.get(CLOUDFLARE_STATUS_API, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data.get("components", [])
    except requests.RequestException as e:
        print(f"ERROR: Failed to fetch Cloudflare status: {e}")
        return []


def filter_african_regions(components: List[Dict]) -> List[Dict]:
    """Filter components to only African regions using group structure"""
    african_components = []
    
    # First, find the Africa group ID
    africa_group_id = None
    for component in components:
        name = component.get("name", "")
        # Look for the Africa group (it's a parent component)
        if name == "Africa":
            africa_group_id = component.get("id")
            print(f"🌍 Found Africa group: {name} (ID: {africa_group_id})")
            break
    
    if not africa_group_id:
        print("WARNING: Could not find Africa group, trying name-based matching...")
        # Fallback to name-based matching if group not found
        african_keywords = [
            "Ghana", "Algeria", "Madagascar", "South Africa", "Senegal", 
            "Tanzania", "Djibouti", "Botswana", "Zimbabwe", "Rwanda",
            "Nigeria", "Angola", "Mozambique", "Kenya", "Tunisia",
            "Egypt", "Zambia", "Morocco", "Mauritius", "Congo",
            "Namibia", "Ivory Coast", "Uganda", "Ethiopia", "Malawi",
            "Burkina Faso", "Réunion", "Reunion", "Abidjan"
        ]
        for component in components:
            name = component.get("name", "")
            for keyword in african_keywords:
                if keyword.lower() in name.lower():
                    african_components.append(component)
                    break
        return african_components
    
    # Get all components that belong to the Africa group
    for component in components:
        if component.get("group_id") == africa_group_id:
            african_components.append(component)
    
    return african_components


def load_previous_state() -> Dict:
    """Load previous state from file"""
    try:
        if os.path.exists(STATE_FILE):
            with open(STATE_FILE, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        print(f"WARNING: Could not load previous state: {e}")
    return {}


def save_current_state(components: List[Dict]):
    """Save current state to file"""
    state = {}
    for component in components:
        component_id = component.get("id", "")
        state[component_id] = {
            "name": component.get("name", ""),
            "status": component.get("status", ""),
            "updated_at": component.get("updated_at", ""),
        }
    
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except IOError as e:
        print(f"WARNING: Could not save state: {e}")


def send_incident_io_alert(component: Dict, previous_status: str):
    """Send alert to incident.io"""
    
    if not INCIDENT_IO_WEBHOOK:
        print("WARNING: INCIDENT_IO_WEBHOOK not configured")
        return
    
    current_status = component.get("status", "unknown")
    component_name = component.get("name", "Unknown Component")
    component_id = component.get("id", "unknown")
    updated_at = component.get("updated_at", datetime.utcnow().isoformat())
    
    # Determine severity based on status
    severity_map = {
        "operational": "info",
        "re_routed": "warning",
        "partially_re_routed": "warning", 
        "degraded_performance": "warning",
        "partial_outage": "error",
        "major_outage": "critical",
        "under_maintenance": "info",
    }
    
    severity = severity_map.get(current_status, "warning")
    
    # Create unique deduplication key
    dedup_key = hashlib.md5(f"{component_id}-{current_status}".encode()).hexdigest()
    
    # Build the alert payload for incident.io
    payload = {
        "dedup_key": dedup_key,
        "title": f"Cloudflare {component_name}: {current_status.replace('_', ' ').title()}",
        "description": f"""
Cloudflare region status change detected:

**Region:** {component_name}
**Previous Status:** {previous_status.replace('_', ' ').title()}
**Current Status:** {current_status.replace('_', ' ').title()}
**Changed At:** {updated_at}

[View Cloudflare Status Page](https://www.cloudflarestatus.com)
        """.strip(),
        "status": "firing" if current_status != "operational" else "resolved",
        "metadata": {
            "region": component_name,
            "component_id": component_id,
            "previous_status": previous_status,
            "current_status": current_status,
            "source": "cloudflare-africa-monitor",
        },
        "source_url": "https://www.cloudflarestatus.com",
    }
    
    headers = {
        "Content-Type": "application/json",
    }
    
    # Add authorization if secret is provided
    if INCIDENT_IO_SECRET:
        headers["Authorization"] = f"Bearer {INCIDENT_IO_SECRET}"
    
    try:
        response = requests.post(
            INCIDENT_IO_WEBHOOK,
            json=payload,
            headers=headers,
            timeout=30
        )
        
        if response.status_code in [200, 201, 202]:
            print(f"✅ Alert sent to incident.io for {component_name}")
        else:
            print(f"⚠️  incident.io response: {response.status_code} - {response.text}")
            
    except requests.RequestException as e:
        print(f"ERROR: Failed to send alert to incident.io: {e}")


def main():
    """Main monitoring function"""
    print("=" * 60)
    print(f"🔍 Starting Cloudflare Africa monitoring")
    print(f"📅 Time: {datetime.utcnow().isoformat()}Z")
    print("=" * 60)
    
    # Fetch current status
    print("\n📡 Fetching status from Cloudflare API...")
    all_components = get_cloudflare_status()
    
    if not all_components:
        print("ERROR: No components retrieved from Cloudflare API")
        return 1
    
    print(f"📊 Retrieved {len(all_components)} total components")
    
    # Filter to African regions
    african_components = filter_african_regions(all_components)
    print(f"🌍 Found {len(african_components)} African region components")
    
    if not african_components:
        print("WARNING: No African regions found in Cloudflare components")
        return 1
    
    # Load previous state
    previous_state = load_previous_state()
    
    # Check each region
    print("\n" + "-" * 60)
    print("📋 Current Status of African Regions:")
    print("-" * 60)
    
    alerts_sent = 0
    for component in sorted(african_components, key=lambda x: x.get("name", "")):
        component_id = component.get("id", "")
        component_name = component.get("name", "Unknown")
        current_status = component.get("status", "unknown")
        
        # Get previous status
        previous_data = previous_state.get(component_id, {})
        previous_status = previous_data.get("status", "unknown")
        
        # Status indicator
        status_emoji = "✅" if current_status == "operational" else "⚠️"
        
        print(f"{status_emoji} {component_name}: {current_status}")
        
        # Check if status changed
        if previous_status == "unknown":
            # First run, just log
            pass
        elif previous_status != current_status:
            print(f"   🔔 STATUS CHANGE: {previous_status} → {current_status}")
            
            # Send alert to incident.io
            send_incident_io_alert(component, previous_status)
            alerts_sent += 1
    
    # Save current state for next run
    save_current_state(african_components)
    
    # Summary
    print("\n" + "=" * 60)
    print("📊 Summary:")
    print(f"   • Regions monitored: {len(african_components)}")
    print(f"   • Alerts sent: {alerts_sent}")
    print("=" * 60)
    print("✅ Monitoring complete")
    
    return 0


if __name__ == "__main__":
    exit(main())
