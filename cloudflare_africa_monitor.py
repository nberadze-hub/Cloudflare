import os
import sys
import json
import requests
from datetime import datetime, timezone

# ---------------- Configuration ----------------
SUMMARY_URL = "https://www.cloudflarestatus.com/api/v2/summary.json"
SLACK_WEBHOOK_URL = os.environ.get("SLACK_WEBHOOK_URL")

STATE_FILE = "cloudflare_state.json"

# Set to False if you want tagging ONLY on new incidents
ALWAYS_TAG_CHANNEL = True

INCIDENT_STATUS_LABELS = {
    "investigating": "Investigating",
    "identified": "Identified",
    "monitoring": "Monitoring",
    "resolved": "Resolved",
    "postmortem": "Postmortem",
}

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
            json.dump(state, f, indent=2)
    except Exception as e:
        print(f"⚠️ Could not save state file: {e}")


# ---------------- Slack ----------------
def send_slack_alert(page_indicator, new_or_changed, resolved):
    if not SLACK_WEBHOOK_URL:
        print("⚠️ SLACK_WEBHOOK_URL not set")
        return

    tag = "<!channel> " if (ALWAYS_TAG_CHANNEL or new_or_changed) else ""
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    blocks = [
        {
            "type": "header",
            "text": {"type": "plain_text", "text": "☁️ Cloudflare Incident Update", "emoji": True},
        },
        {"type": "divider"},
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": f"*Status Page Indicator:* `{page_indicator}`",
            },
        },
        {"type": "divider"},
    ]

    if new_or_changed:
        blocks.append(
            {"type": "section", "text": {"type": "mrkdwn", "text": "*🔴 Active / Updated Incidents*"}}
        )
        body = ""
        for inc in new_or_changed:
            label = INCIDENT_STATUS_LABELS.get(inc["status"], inc["status"])
            body += (
                f"• *{inc['name']}*\n"
                f"  Status: _{label}_ | Impact: `{inc['impact']}`\n"
                f"  {inc.get('shortlink') or inc.get('url')}\n"
            )
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})
        blocks.append({"type": "divider"})

    if resolved:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": "*✅ Resolved*"}})
        body = ""
        for inc in resolved:
            body += f"• *{inc['name']}*\n  {inc.get('shortlink') or inc.get('url')}\n"
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": body}})
        blocks.append({"type": "divider"})

    blocks.append(
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"🕒 {now_utc} | <https://www.cloudflarestatus.com/|Cloudflare Status>",
                }
            ],
        }
    )

    payload = {
        "text": f"{tag}Cloudflare Status Update",
        "blocks": blocks,
    }

    try:
        requests.post(SLACK_WEBHOOK_URL, json=payload, timeout=10).raise_for_status()
        print("-> Slack alert sent.")
    except Exception as e:
        print(f"-> Slack send failed: {e}")


# ---------------- Cloudflare logic ----------------
def fetch_summary():
    r = requests.get(SUMMARY_URL, timeout=20)
    r.raise_for_status()
    return r.json()


def normalize_state(summary):
    page_indicator = summary.get("status", {}).get("indicator", "unknown")
    incidents = summary.get("incidents", []) or []

    inc_state = {}
    for inc in incidents:
        inc_id = inc.get("id")
        if not inc_id:
            continue

        inc_state[inc_id] = {
            "name": inc.get("name", "Unnamed incident"),
            "status": inc.get("status", "unknown"),
            "impact": inc.get("impact", "unknown"),
            "shortlink": inc.get("shortlink"),
            "url": inc.get("url"),
        }

    return {"page_indicator": page_indicator, "incidents": inc_state}


def diff_state(prev, curr):
    prev_inc = (prev or {}).get("incidents", {})
    curr_inc = (curr or {}).get("incidents", {})

    new_or_changed = []
    resolved = []

    for inc_id, inc in curr_inc.items():
        if inc["impact"] not in ALERT_IMPACTS:
            continue

        prev_entry = prev_inc.get(inc_id)
        if inc["status"] != "resolved":
            if prev_entry is None or prev_entry["status"] != inc["status"]:
                new_or_changed.append(inc)

    for inc_id, prev_entry in prev_inc.items():
        if prev_entry["status"] != "resolved":
            curr_entry = curr_inc.get(inc_id)
            if curr_entry is None or curr_entry["status"] == "resolved":
                resolved.append(prev_entry)

    return new_or_changed, resolved


# ---------------- Main ----------------
def main():
    print(f"Check started at {datetime.now(timezone.utc)}")

    prev_state = load_previous_state()

    try:
        summary = fetch_summary()
        curr_state = normalize_state(summary)

        new_or_changed, resolved = diff_state(prev_state, curr_state)

        if new_or_changed or resolved:
            send_slack_alert(
                curr_state["page_indicator"],
                new_or_changed,
                resolved,
            )
        else:
            print("No changes detected.")

        save_current_state(curr_state)

    except Exception as e:
        print(f"❌ Fatal error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
