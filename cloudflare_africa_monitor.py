import os
import sys
import json
import requests
from datetime import datetime, timezone

# ---------------- Configuration ----------------
SUMMARY_URL = "https://www.cloudflarestatus.com/api/v2/summary.json"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

STATE_FILE = "cloudflare_incident_state.json"

# Tag slack only when a NEW incident appears (not on resolve-only)
TAG_ON_NEW = True
SLACK_MENTION = "<!channel> "

# Only alert when impact is meaningful (Cloudflare uses: none/minor/major/critical)
ALERT_IMPACTS = {"minor", "major", "critical"}

INCIDENT_STATUS_LABELS = {
    "investigating": "Investigating",
    "identified": "Identified",
    "monitoring": "Monitoring",
    "resolved": "Resolved",
    "postmortem": "Postmortem",
}


# ---------------- State helpers ----------------
def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"⚠️ Could not save state: {e}")


# ---------------- Slack ----------------
def send_slack_incident_message(incident, is_resolved=False):
    if not SLACK_WEBHOOK_URL:
        print("⚠️ SLACK_WEBHOOK_URL not set; skipping Slack.")
        return

    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    name = incident.get("name", "Unnamed incident")
    status = incident.get("status", "unknown")
    impact = incident.get("impact", "unknown")
    url = incident.get("shortlink") or incident.get("url") or "https://www.cloudflarestatus.com/"

    status_label = INCIDENT_STATUS_LABELS.get(status, status)

    if is_resolved:
        header_text = "✅ Cloudflare Incident Resolved"
        title_line = f"*{name}*"
        details = f"Status: _{status_label}_ | Impact: `{impact}`\n{url}"
        mention = ""  # typically no channel tag on resolve-only
        emoji_text = "Cloudflare incident resolved"
    else:
        header_text = "🔴 Cloudflare Incident Detected"
        title_line = f"*{name}*"
        details = f"Status: _{status_label}_ | Impact: `{impact}`\n{url}"
        mention = SLACK_MENTION if TAG_ON_NEW else ""
        emoji_text = "Cloudflare incident detected"

    blocks = [
        {"type": "header", "text": {"type": "plain_text", "text": header_text, "emoji": True}},
        {"type": "divider"},
        {"type": "section", "text": {"type": "mrkdwn", "text": title_line}},
        {"type": "section", "text": {"type": "mrkdwn", "text": details}},
        {"type": "divider"},
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"🕒 {now_utc} | <https://www.cloudflarestatus.com/|Status Page>"}
            ],
        },
    ]

    payload = {"text": f"{mention}{emoji_text}", "blocks": blocks}

    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        print("-> Slack message sent.")
    except Exception as e:
        print(f"-> Slack send failed: {e}")


# ---------------- Cloudflare ----------------
def fetch_summary():
    r = requests.get(SUMMARY_URL, timeout=20)
    r.raise_for_status()
    return r.json()


def pick_primary_incident(summary_json):
    """
    Pick ONE "primary" incident to alert on.
    We choose the first unresolved incident with impact in ALERT_IMPACTS.
    (Statuspage usually lists most relevant first.)
    """
    incidents = summary_json.get("incidents", []) or []
    for inc in incidents:
        status = inc.get("status", "unknown")
        impact = inc.get("impact", "unknown")
        if status != "resolved" and impact in ALERT_IMPACTS:
            return inc
    return None


# ---------------- Main logic ----------------
def main():
    print(f"Check started at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")

    prev = load_state()
    prev_active_id = prev.get("active_incident_id")  # only track ONE incident at a time

    try:
        summary = fetch_summary()
        active_incident = pick_primary_incident(summary)

        # CASE 1: There is an active incident now
        if active_incident:
            active_id = active_incident.get("id")

            # If we previously had no active incident tracked -> NEW incident => send ONE message
            if not prev_active_id:
                print(f"🔴 New incident: {active_incident.get('name')}")
                send_slack_incident_message(active_incident, is_resolved=False)
                save_state({"active_incident_id": active_id})
            else:
                # We already alerted about an active incident; do nothing (no status-label updates)
                if prev_active_id == active_id:
                    print("Active incident already alerted; skipping updates.")
                else:
                    # A different incident became primary while one was tracked.
                    # To keep behavior strict: treat this as NEW incident and replace tracking.
                    print(f"🔴 New incident replaced previous: {active_incident.get('name')}")
                    send_slack_incident_message(active_incident, is_resolved=False)
                    save_state({"active_incident_id": active_id})

        # CASE 2: No active incident now
        else:
            # If we previously tracked an incident -> it is resolved => send ONE resolved message
            if prev_active_id:
                # Find details for the previous incident from summary (may be missing), send minimal resolution message
                resolved_inc = {"name": "Incident", "status": "resolved", "impact": "unknown", "url": "https://www.cloudflarestatus.com/"}
                # Try to locate it in summary incidents (sometimes resolved still listed)
                for inc in (summary.get("incidents", []) or []):
                    if inc.get("id") == prev_active_id:
                        resolved_inc = inc
                        break
                resolved_inc["status"] = "resolved"

                print("✅ Incident resolved (no active incidents).")
                send_slack_incident_message(resolved_inc, is_resolved=True)
                save_state({"active_incident_id": None})
            else:
                print("No active incidents and nothing to resolve; no alert.")

    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
