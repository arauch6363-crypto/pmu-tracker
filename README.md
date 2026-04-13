# PMU Odds Tracker

Automatically tracks live PMU horse racing odds every 15 minutes during racing hours, and saves a daily history to this repository.

## How it works

1. **Railway** triggers the script every 15 min between 08:00–20:00 (UTC)
2. The script fetches odds for all races of the day from the PMU API
3. Each snapshot is appended to a daily JSON file in `/history/`
4. The file is committed and pushed back to this repo automatically

Each run takes ~30 seconds and costs fractions of a cent.

---

## File structure

```
pmu-tracker/
├── pmu_odds_tracker.py   ← main script
├── railway.toml          ← Railway cron config
├── requirements.txt      ← Python dependencies
└── history/
    ├── odds_2026-04-11.json
    ├── odds_2026-04-12.json
    └── ...
```

---

## History file format

```json
{
  "2026-04-11 09:00": {
    "R1/C1": {
      "hippodrome": "VINCENNES",
      "label": "Prix de la Marne",
      "heure": "13:30",
      "odds": {
        "#3 GALAXY ROAD": 2.4,
        "#7 BELLE ETOILE": 5.1
      }
    }
  },
  "2026-04-11 09:15": { ... }
}
```

---

## Setup

### 1. Fork / clone this repo to your GitHub account

### 2. Create a GitHub Personal Access Token
- GitHub → Settings → Developer Settings → Personal Access Tokens → Tokens (classic)
- Scopes needed: `repo` (full)
- Copy the token

### 3. Deploy to Railway
- Go to [railway.app](https://railway.app) → New Project → Deploy from GitHub repo
- Select this repo
- Railway will detect `railway.toml` and set up the cron job automatically

### 4. Set environment variables in Railway
In your Railway project → Variables, add:

| Variable | Value |
|---|---|
| `GITHUB_TOKEN` | your Personal Access Token from step 2 |
| `GITHUB_REPO` | `your-username/pmu-tracker` |

### 5. Done!
Railway will run the script every 15 min during racing hours.
Check the `/history/` folder in this repo to see data accumulating.

---

## Reading the data in Google Colab

```python
import requests, json

# Replace with your actual GitHub username and repo name
REPO = "your-username/pmu-tracker"
DATE = "2026-04-11"

url  = f"https://raw.githubusercontent.com/{REPO}/main/history/odds_{DATE}.json"
data = requests.get(url).json()

# See all snapshot timestamps
print(list(data.keys()))

# Latest snapshot
latest = list(data.values())[-1]

# Odds for a specific race
print(latest["R1/C2"]["odds"])

# All races in latest snapshot
for race, info in latest.items():
    print(f"{race}  {info['hippodrome']}  {info['heure']}")
    for horse, odds in sorted(info["odds"].items(), key=lambda x: x[1]):
        print(f"   {horse:<30} {odds:.1f}")
```

---

## Adjusting racing hours (timezone)

Railway runs in UTC. France is UTC+1 (winter) or UTC+2 (summer).
Adjust the cron schedule in `railway.toml` accordingly:

- Winter (CET = UTC+1): `*/15 7-19 * * *`
- Summer (CEST = UTC+2): `*/15 6-18 * * *`
