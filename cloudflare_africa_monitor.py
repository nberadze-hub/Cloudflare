import os
import sys
import json
import requests
from datetime import datetime, timezone

# ---------------- Configuration ----------------
SUMMARY_URL = "https://www.cloudflarestatus.com/api/v2/summary.json"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

STATE_FILE = "cloudflare_state.json"

STATUS_MAPPING = {
    "operational": "Operational",
    "partial_outage": "Partial Outage",
    "under_maintenance": "Under Maintenance",
    "degraded_performance": "Degraded Performance",
    "major_outage": "Major Outage",
}

INCIDENT_STATUS_LABELS = {
    "investigating": "Investigating",
    "identified": "Identified",
    "monitoring": "Monitoring",
    "resolved": "Resolved",
    "postmortem": "Postmortem",
}

# Optional: Only alert on incidents whose impact is not "none"
# Cloudflare often uses: none, minor, major, critical
ALERT_IMPACTS = {"minor", "major", "critical"}


# ---------------- State helpers ----------------
def load_previous_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}


def save_current_state(state):
    try:
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"⚠️ Warning: Could not save state file: {e}")


# ---------------- Slack ----------------
def send_slack_alert(page_indicator, new_or_changed, resolved):
    """
    Send ONE Slack message summarizing CHANGES since last check.
    Mentions <!channel> only when a NEW/CHANGED unresolved incident appears.
    """
    if not SLACK_WEBHOOK_URL:
        print("⚠️ SLACK_WEBHOOK_URL not set; skipping Slack send.")
        return

    mention = "<!channel> " if new_or_changed else ""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "☁️ Cloudflare Status Update", "emoji": True},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Page status indicator:* `{page_indicator}`",
            },
        },
        {"type": "divider"},
    ]

    if new_or_changed:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "*🔴 New / Updated Incidents*"}}
        )
        body = ""
        for inc in new_or_changed:
            status_label = INCIDENT_STATUS_LABELS.get(inc["status"], inc["status"])
            impact = inc.get("impact", "unknown")
            url = inc.get("shortlink") or inc.get("url") or "https://www.cloudflarestatus.com/"
            body += f"• *{inc['name']}* — _{status_label}_ | impact: `{impact}`\n  {url}\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})
        blocks.append({"type": "divider"})

    if resolved:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*✅ Resolved*"}})
        body = ""
        for inc in resolved:
            url = inc.get("shortlink") or inc.get("url") or "https://www.cloudflarestatus.com/"
            body += f"• *{inc['name']}*\n  {url}\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"🕒 {now_utc} | <https://www.cloudflarestatus.com/|Status Page>",
                }
            ],
        }
    )

    payload = {"text": f"{mention}Cloudflare Status Update", "blocks": blocks}

    try:
        resp = requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10)
        resp.raise_for_status()
        print("-> Slack alert sent.")
    except Exception as e:
        print(f"-> Error sending Slack: {e}")


# ---------------- Cloudflare fetch + diff ----------------
def fetch_summary():
    r = requests.get(SUMMARY_URL, timeout=20)
    r.raise_for_status()
    return r.json()


def normalize_state(summary_json):
    """
    Build a state dict we can diff between runs.

    We track:
      - page indicator (none/minor/major/critical)
      - incidents by ID (status, impact)
    """
    page_indicator = summary_json.get("status", {}).get("indicator", "unknown")
    incidents = summary_json.get("incidents", []) or []

    inc_state = {}
    for inc in incidents:
        inc_id = inc.get("id")
        if not inc_id:
            continue

        status = inc.get("status", "unknown")          # investigating/identified/monitoring/resolved/...
        impact = inc.get("impact", "unknown")          # none/minor/major/critical

        # Helpful URLs (summary usually includes "shortlink")
        inc_state[inc_id] = {
            "name": inc.get("name", "Unnamed incident"),
            "status": status,
            "impact": impact,
            "shortlink": inc.get("shortlink"),
            "url": inc.get("url"),
        }

    return {"page_indicator": page_indicator, "incidents": inc_state}


def diff_state(prev, curr):
    prev_inc = (prev or {}).get("incidents", {}) or {}
    curr_inc = (curr or {}).get("incidents", {}) or {}

    new_or_changed = []
    resolved = []

    # New or changed incidents (unresolved only)
    for inc_id, inc in curr_inc.items():
        status = inc.get("status", "unknown")
        impact = inc.get("impact", "unknown")

        # Optional filter: only alert for meaningful impacts
        if impact in {"none"}:
            continue
        if ALERT_IMPACTS and impact not in ALERT_IMPACTS:
            continue

        prev_entry = prev_inc.get(inc_id)
        if status != "resolved":
            if prev_entry is None:
                new_or_changed.append(inc)
            else:
                # status change (or impact change)
                if (prev_entry.get("status") != status) or (prev_entry.get("impact") != impact):
                    new_or_changed.append(inc)

    # Resolved incidents (previously unresolved, now resolved or disappeared)
    for inc_id, prev_entry in prev_inc.items():
        prev_status = prev_entry.get("status", "unknown")
        if prev_status == "resolved":
            continue

        curr_entry = curr_inc.get(inc_id)
        if curr_entry is None:
            # Sometimes resolved incidents drop from summary; treat as resolved
            resolved.append(prev_entry)
        else:
            if curr_entry.get("status") == "resolved":
                resolved.append(curr_entry)

    return new_or_changed, resolved


# ---------------- Main ----------------
def main():
    print(f"Starting check at {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}...")

    prev_state = load_previous_state()

    try:
        summary = fetch_summary()
        curr_state = normalize_state(summary)

        page_indicator = curr_state.get("page_indicator", "unknown")
        new_or_changed, resolved = diff_state(prev_state, curr_state)

        # Log a quick view
        if new_or_changed:
            for inc in new_or_changed:
                print(f"🔴 Incident: {inc['name']} -> {inc.get('status')} (impact: {inc.get('impact')})")
        if resolved:
            for inc in resolved:
                print(f"✅ Resolved: {inc['name']}")

        if new_or_changed or resolved:
            send_slack_alert(page_indicator, new_or_changed, resolved)
        else:
            print("No incident changes detected (per summary endpoint).")

        save_current_state(curr_state)
        print("Done. State saved.")

    except Exception as e:
        print(f"❌ Critical Error: {str(e)}")
        sys.exit(1)


if __name__ == "__main__":
    main()
