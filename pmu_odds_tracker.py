"""
PMU Odds Tracker
================
Fetches a single snapshot of all race odds from the PMU API
and appends it to a daily history file, then pushes to GitHub.

Designed to be triggered every 15 min by Railway Cron.

Odds data per horse:
  - odds:      win odds (float)
  - tendance:  "+" = drifting, "-" = shortening
  - magnitude: strength of the move (float)
  - favoris:   True if currently the favourite (bool)
"""

import requests
import json
import os
import subprocess
from datetime import datetime

# ── Config ────────────────────────────────────────────────────────────────────
BASE_URL    = "https://offline.turfinfo.api.pmu.fr/rest/client/7/programme"
HEADERS     = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
HISTORY_DIR = "history"
# ──────────────────────────────────────────────────────────────────────────────


def get_today_date() -> str:
    """Return today's date in PMU format: DDMMYYYY"""
    return datetime.now().strftime("%d%m%Y")


def get_history_filename() -> str:
    """One JSON file per day, e.g. history/odds_2026-04-11.json"""
    today = datetime.now().strftime("%Y-%m-%d")
    return os.path.join(HISTORY_DIR, f"odds_{today}.json")


def fetch_all_races(date: str) -> dict:
    """
    Fetch odds for every race on the given date.
    Returns:
    {
      "R1/C1": {
        "hippodrome": "AUTEUIL",
        "label":      "PRIX GASTON BRANERE",
        "heure":      "13:15",
        "horses": {
          "#1 NO LIMITS STEVE": {
            "odds":      7.6,
            "tendance":  "+",
            "magnitude": 1.33,
            "favoris":   False
          },
          ...
        }
      },
      ...
    }
    Only includes horses with non-null odds.
    Only includes races that have at least one odd available.
    """
    results = {}

    try:
        r = requests.get(f"{BASE_URL}/{date}", headers=HEADERS, timeout=10)
        r.raise_for_status()
        programme = r.json().get("programme", {}).get("reunions", [])
    except Exception as e:
        print(f"[ERROR] Could not fetch programme: {e}")
        return results

    for reunion in programme:
        r_num = f"R{reunion.get('numOfficiel', '?')}"
        hippo = reunion.get("hippodrome", {}).get("libelleCourt", "")

        for course in reunion.get("courses", []):
            c_num = f"C{course.get('numOrdre', '?')}"
            label = course.get("libelle", "")
            heure = course.get("heureDepart", "")

            # Convert millisecond timestamp to HH:MM string
            if isinstance(heure, int):
                heure = datetime.fromtimestamp(heure / 1000).strftime("%H:%M")

            try:
                url  = f"{BASE_URL}/{date}/{r_num}/{c_num}/participants"
                resp = requests.get(url, headers=HEADERS, timeout=10)
                resp.raise_for_status()
                participants = resp.json().get("participants", [])

                horses = {}
                for p in participants:
                    name    = f"#{p.get('numPmu', '?')} {p.get('nom', '?')}"
                    rapport = p.get("dernierRapportDirect", {})  # ← correct field

                    if isinstance(rapport, dict):
                        win       = rapport.get("rapport")
                        tendance  = rapport.get("indicateurTendance", "")
                        magnitude = rapport.get("nombreIndicateurTendance")
                        favoris   = rapport.get("favoris", False)
                    else:
                        win, tendance, magnitude, favoris = None, "", None, False

                    # Only store horses with non-null odds
                    if win is not None:
                        horses[name] = {
                            "odds":      win,
                            "tendance":  tendance,   # "+" drifting, "-" shortening
                            "magnitude": magnitude,  # strength of move
                            "favoris":   favoris,    # True = current favourite
                        }

                # Only store races with at least one odd available
                if horses:
                    key = f"{r_num}/{c_num}"
                    results[key] = {
                        "hippodrome": hippo,
                        "label":      label,
                        "heure":      heure,
                        "horses":     horses,
                    }
                    fav = next((n for n, d in horses.items() if d["favoris"]), "?")
                    print(f"  ✅ {key:<8} {hippo:<12} {heure}  {len(horses)} horses  fav: {fav}")

            except Exception as e:
                print(f"  [ERROR] {r_num}/{c_num}: {e}")

    return results


def load_history(filepath: str) -> dict:
    """Load existing history file, or return empty dict."""
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(filepath: str, history: dict):
    """Save history dict to JSON file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def push_to_github(filepath: str, timestamp: str):
    """Upload file directly to GitHub via API — no git required."""
    import base64

    token = os.environ.get("GITHUB_TOKEN")
    repo  = os.environ.get("GITHUB_REPO")  # e.g. "arauch6363-crypto/pmu-tracker"

    if not token or not repo:
        print("[WARN] GITHUB_TOKEN or GITHUB_REPO not set — skipping.")
        return

    headers = {
        "Authorization": f"token {token}",
        "Accept":        "application/vnd.github.v3+json",
    }

    # Read the file we just saved
    with open(filepath, "rb") as f:
        content = base64.b64encode(f.read()).decode("utf-8")

    # GitHub API path — must match exactly the path in the repo
    api_path = filepath.replace("\\", "/")  # fix Windows paths if any
    url      = f"https://api.github.com/repos/{repo}/contents/{api_path}"

    # Check if file already exists (we need its SHA to update it)
    r   = requests.get(url, headers=headers)
    sha = r.json().get("sha")  # None if file doesn't exist yet

    # Create or update the file
    payload = {
        "message": f"📊 Odds snapshot {timestamp}",
        "content": content,
    }
    if sha:
        payload["sha"] = sha  # required for updates

    r = requests.put(url, headers=headers, json=payload)

    if r.status_code in (200, 201):
        print(f"  ✅ Pushed to GitHub: {api_path}")
    else:
        print(f"  [ERROR] GitHub API: {r.status_code} — {r.json().get('message')}")


def print_summary(races: dict):
    """Print a readable summary of all captured odds."""
    print(f"\n{'─' * 60}")
    for key, race in races.items():
        print(f"\n  🏇 {key}  {race['hippodrome']}  {race['heure']}  {race['label']}")
        for name, d in sorted(race["horses"].items(), key=lambda x: x[1]["odds"]):
            fav_marker = " ⭐" if d["favoris"] else ""
            trend      = d["tendance"] if d["tendance"] else " "
            print(f"     {trend} {name:<30} {d['odds']:.1f}{fav_marker}")
    print(f"\n{'─' * 60}")


def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    date      = get_today_date()

    print(f"\n{'═' * 50}")
    print(f"  📡 PMU Snapshot  —  {timestamp}")
    print(f"{'═' * 50}\n")

    races = fetch_all_races(date)

    if not races:
        print("\n⚠️  No odds available yet for any race. Exiting.")
        return

    print_summary(races)
    print(f"\n  {len(races)} races captured.")

    filepath = get_history_filename()
    history  = load_history(filepath)
    history[timestamp] = races
    save_history(filepath, history)
    print(f"  💾 Saved to {filepath}  ({len(history)} snapshots today)")

    push_to_github(filepath, timestamp)

    print(f"\n✅ Done.\n")


if __name__ == "__main__":
    main()
