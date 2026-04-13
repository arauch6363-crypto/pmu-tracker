"""
PMU Odds Tracker
================
Fetches a single snapshot of all race odds from the PMU API
and appends it to a daily history file, then pushes to GitHub.

Designed to be triggered every 15 min by Railway Cron.
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
    Returns { "R1/C1": { "#3 HORSE NAME": 2.4, ... }, ... }
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
            c_num  = f"C{course.get('numOrdre', '?')}"
            label  = course.get("libelle", "")
            heure  = course.get("heureDepart", "")

            # Convert millisecond timestamp to HH:MM string
            if isinstance(heure, int):
                heure = datetime.fromtimestamp(heure / 1000).strftime("%H:%M")

            try:
                url  = f"{BASE_URL}/{date}/{r_num}/{c_num}/participants"
                resp = requests.get(url, headers=HEADERS, timeout=10)
                resp.raise_for_status()
                participants = resp.json().get("participants", [])

                odds = {}
                for p in participants:
                    name    = f"#{p.get('numPmu', '?')} {p.get('nom', '?')}"
                    rapport = p.get("rapportDirect", {})

                    # Extract win odds from nested or flat structure
                    if isinstance(rapport, dict):
                        win = rapport.get("simple") or rapport.get("rapport")
                    else:
                        win = rapport

                    # Fallback to top-level rapport field
                    if win is None:
                        win = p.get("rapport")

                    # Only store non-null values
                    if win is not None:
                        odds[name] = win

                # Only store races that have at least one odd
                if odds:
                    key = f"{r_num}/{c_num}"
                    results[key] = {
                        "hippodrome": hippo,
                        "label":      label,
                        "heure":      heure,
                        "odds":       odds,
                    }
                    print(f"  ✅ {key}  {hippo}  {heure}  — {len(odds)} horses")

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
    """Commit and push the updated history file to GitHub."""
    token = os.environ.get("GITHUB_TOKEN")
    repo  = os.environ.get("GITHUB_REPO")   # e.g. "username/pmu-tracker"

    if not token or not repo:
        print("[WARN] GITHUB_TOKEN or GITHUB_REPO not set — skipping git push.")
        return

    # Set remote URL with token authentication
    remote = f"https://{token}@github.com/{repo}.git"

    cmds = [
        ["git", "config", "user.name",  "railway-bot"],
        ["git", "config", "user.email", "railway-bot@noreply.github.com"],
        ["git", "remote", "set-url", "origin", remote],
        ["git", "pull",   "--rebase", "origin", "main"],
        ["git", "add",    filepath],
        ["git", "commit", "-m", f"📊 Odds snapshot {timestamp}"],
        ["git", "push",   "origin", "main"],
    ]

    for cmd in cmds:
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            # "nothing to commit" is not a real error
            if "nothing to commit" in result.stdout + result.stderr:
                print("  [INFO] Nothing new to commit.")
                return
            print(f"  [ERROR] {' '.join(cmd)}: {result.stderr.strip()}")
            return

    print(f"  ✅ Pushed to GitHub: {filepath}")


def main():
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    date      = get_today_date()

    print(f"\n{'═' * 50}")
    print(f"  📡 PMU Snapshot  —  {timestamp}")
    print(f"{'═' * 50}\n")

    # Fetch all races
    races = fetch_all_races(date)

    if not races:
        print("\n⚠️  No odds available yet for any race. Exiting.")
        return

    print(f"\n  {len(races)} races with odds captured.")

    # Load today's history, append snapshot, save
    filepath = get_history_filename()
    history  = load_history(filepath)
    history[timestamp] = races
    save_history(filepath, history)
    print(f"  💾 Saved to {filepath}  ({len(history)} snapshots today)")

    # Push to GitHub
    push_to_github(filepath, timestamp)

    print(f"\n✅ Done.\n")


if __name__ == "__main__":
    main()
