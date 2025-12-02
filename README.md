# Cloudflare Africa Region Monitor

Monitors Cloudflare status for all African data center regions and sends alerts to incident.io when status changes.

## Features

- ✅ Monitors 25+ African Cloudflare regions
- ✅ Detects ANY status change (operational, re_routed, degraded, outage, etc.)
- ✅ Sends alerts to incident.io with full context
- ✅ Runs every 5 minutes via GitHub Actions
- ✅ Free to run (uses GitHub Actions free tier)
- ✅ Maintains state between runs

## Quick Setup (5 minutes)

### Step 1: Create GitHub Repository

1. Go to https://github.com/new
2. Name: `cloudflare-africa-monitor`
3. Set to **Private**
4. Click **Create repository**

### Step 2: Upload Files

Upload these files to your repository:

```
your-repo/
├── cloudflare_africa_monitor.py
├── requirements.txt
├── README.md
└── .github/
    └── workflows/
        └── monitor.yml
```

**Important:** The `monitor.yml` file MUST be in `.github/workflows/` folder.

To create the folder structure:
1. Click "Add file" → "Create new file"
2. Type `.github/workflows/monitor.yml` as the filename
3. Paste the contents of monitor.yml
4. Click "Commit new file"

### Step 3: Add Secrets

1. Go to your repository **Settings**
2. Click **Secrets and variables** → **Actions**
3. Click **New repository secret**

Add these two secrets:

| Secret Name | Value |
|-------------|-------|
| `INCIDENT_IO_WEBHOOK` | Your incident.io webhook URL |
| `INCIDENT_IO_SECRET` | Your incident.io secret token |

### Step 4: Enable GitHub Actions

1. Click the **Actions** tab
2. Click **"I understand my workflows, go ahead and enable them"**

### Step 5: Test

1. Click on **Cloudflare Africa Monitor** workflow
2. Click **Run workflow** → **Run workflow**
3. Wait ~20 seconds and refresh
4. Check the logs to see it working!

## African Regions Monitored

- Accra, Ghana (ACC)
- Algiers, Algeria (ALG)
- Annaba, Algeria (AAE)
- Antananarivo, Madagascar (TNR)
- Bujumbura, Burundi (BJM)
- Cairo, Egypt (CAI)
- Cape Town, South Africa (CPT)
- Casablanca, Morocco (CMN)
- Dakar, Senegal (DKR)
- Dar Es Salaam, Tanzania (DSM)
- Djibouti City, Djibouti (JIB)
- Durban, South Africa (DUR)
- Gaborone, Botswana (GBE)
- Harare, Zimbabwe (HRE)
- Johannesburg, South Africa (JNB)
- Kigali, Rwanda (KGL)
- Lagos, Nigeria (LOS)
- Luanda, Angola (LAD)
- Lusaka, Zambia (LUN)
- Maputo, Mozambique (MPM)
- Mombasa, Kenya (MBA)
- Nairobi, Kenya (NBO)
- Oran, Algeria (ORN)
- Port Louis, Mauritius (MRU)
- Tunis, Tunisia (TUN)

## Status Types Detected

The monitor catches ALL status changes including:

| Status | Severity |
|--------|----------|
| operational | info |
| re_routed | warning |
| partially_re_routed | warning |
| degraded_performance | warning |
| partial_outage | error |
| major_outage | critical |
| under_maintenance | info |

Plus any future status types Cloudflare may add!

## How It Works

1. Every 5 minutes, GitHub Actions runs the script
2. Script fetches current status from Cloudflare API
3. Compares with previous state (cached between runs)
4. If ANY status changed → sends alert to incident.io
5. Saves new state for next comparison

## Troubleshooting

**Workflow not running?**
- Check Actions tab is enabled
- Verify workflow file is in `.github/workflows/monitor.yml`

**No alerts received?**
- Check secrets are set correctly
- Run workflow manually and check logs
- Verify incident.io webhook is active

**Missing regions?**
- Script monitors all African regions in Cloudflare's API
- If a new region is added, it will be detected automatically

## Cost

- GitHub Actions: **FREE** (2,000 minutes/month on free plan)
- Cloudflare API: **FREE**
- incident.io webhooks: **FREE**

**Total: $0/month**

## License

MIT
