"""Fetch current values and 48 h history from Home Assistant and publish the dashboard.

Writes data.json next to index.html and force-pushes both as a single commit to the
gh-pages branch, so the branch never grows. Run every 15 minutes by launchd
(see com.veikkosalminen.home-dashboard.plist).

    python3 update.py            # fetch and publish
    python3 update.py --local    # fetch only, for testing index.html locally
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

HA = "http://192.168.100.50:8123"  # IPv4: homeassistant.local does not resolve for Python here
TOKEN = Path("~/.config/homeassistant/token").expanduser().read_text().strip()
ROOT = Path(__file__).resolve().parent
REMOTE = "https://github.com/veikkosalminen/home-dashboard.git"
HOURS = 48
STEP_MIN = 15

# key: entity id. Only these values leave the house.
ENTITIES = {
    "out_t": "sensor.ulkolampo",
    "out_rh": "sensor.ulkokosteus",
    "out_ah": "sensor.absoluuttinen_kosteus_ulkona",
    "wind": "sensor.tuulen_nopeus",
    "hall_t": "sensor.lampotila_ja_kosteusanturi_lampotila",
    "hall_rh": "sensor.lampotila_ja_kosteusanturi_kosteus",
    "marta_t": "sensor.lampotila_ja_kosteusanturi_lampotila_2",
    "marta_rh": "sensor.lampotila_ja_kosteusanturi_kosteus_2",
    "shower_t": "sensor.lampotila_ja_kosteusanturi_lampotila_3",
    "shower_rh": "sensor.lampotila_ja_kosteusanturi_kosteus_3",
    "in_ah": "sensor.absoluuttinen_kosteus_sisalla",
    "rh_target": "sensor.tavoite_kosteus_sisalla",
    "attic_t": "sensor.ylapohja_lampotila",
    "attic_rh": "sensor.ylapohja_kosteus",
    "attic_ah": "sensor.ylapohja_absoluuttinen_kosteus",
    "attic_dew": "sensor.ylapohja_kastepiste",
    "attic_excess": "sensor.ylapohja_kosteampi_kuin_ulkona",
    "attic_mould": "binary_sensor.ylapohja_homeelle_suotuisa",
    "attic_leak": "binary_sensor.ylapohjaan_vuotaa_sisailmaa",
    "fan_w": "sensor.poistoilma_nykyinen_kulutus",
    "fan_duty": "sensor.poistopumpun_duty_cycle",
    "fan_on_pct": "sensor.topseli_paalla_prosenttia_tanaan",
    "need": "sensor.tarvittava_kokonaisilmanvaihto",
    "hp_w": "sensor.ilmalampopumppu_nykyinen_kulutus",
    "hp_kwh": "sensor.ilmalampopumppu_today_s_consumption",
    "rad_w": "sensor.patterit_nykyinen_kulutus",
    "rad_kwh": "sensor.patterit_today_s_consumption",
    "oil_w": "sensor.oljypoltin_nykyinen_kulutus",
    "oil_kwh": "sensor.oljypoltin_today_s_consumption",
    "fan_kwh": "sensor.poistoilma_today_s_consumption",
}
SERIES = ["out_t", "hall_t", "marta_t", "shower_t", "attic_t",
          "out_rh", "hall_rh", "marta_rh", "shower_rh", "attic_rh",
          "out_ah", "in_ah", "attic_ah", "hp_w", "rad_w", "fan_w"]


def get(path):
    # Apple's curl, not urllib: macOS Local Network privacy blocks Homebrew Python under
    # launchd ("No route to host"). The token goes in on stdin so it is not in argv.
    cfg = f'header = "Authorization: Bearer {TOKEN}"\n'
    r = subprocess.run(["/usr/bin/curl", "-sfS", "--max-time", "30", "-K", "-", HA + path],
                       input=cfg, capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def num(v):
    if v in ("on", "off"):
        return v == "on"
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def fetch():
    states = {s["entity_id"]: s for s in get("/api/states")}
    now = {}
    for key, eid in ENTITIES.items():
        s = states.get(eid)
        if s:
            now[key] = {"v": num(s["state"]), "unit": s["attributes"].get("unit_of_measurement", "")}

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=HOURS)
    ids = ",".join(ENTITIES[k] for k in SERIES)
    q = urllib.parse.urlencode({"filter_entity_id": ids, "end_time": end.isoformat(),
                                "minimal_response": "", "no_attributes": ""})
    hist = get(f"/api/history/period/{urllib.parse.quote(start.isoformat())}?{q}")
    by_id = {h[0]["entity_id"]: h for h in hist if h}

    # resample to a fixed grid: last known value at each step
    steps = int(HOURS * 60 / STEP_MIN) + 1
    grid = [start + timedelta(minutes=STEP_MIN * i) for i in range(steps)]
    series = {}
    for key in SERIES:
        pts = []
        for h in by_id.get(ENTITIES[key], []):
            t = h.get("last_changed") or h.get("last_updated")
            v = num(h.get("state"))
            if t and isinstance(v, float):
                pts.append((datetime.fromisoformat(t), v))
        vals, j, last = [], 0, None
        for g in grid:
            while j < len(pts) and pts[j][0] <= g:
                last = pts[j][1]
                j += 1
            vals.append(last)
        series[key] = vals
    return {"updated": end.isoformat(timespec="seconds"), "start": start.isoformat(timespec="seconds"),
            "step_min": STEP_MIN, "now": now, "series": series}


def publish(data):
    with tempfile.TemporaryDirectory() as d:
        site = Path(d)
        shutil.copy(ROOT / "index.html", site / "index.html")
        (site / "data.json").write_text(json.dumps(data, separators=(",", ":")))
        (site / ".nojekyll").write_text("")
        git = ["git", "-C", d, "-c", "user.name=home-dashboard", "-c", "user.email=noreply@github.com"]
        subprocess.run(git + ["init", "-q", "-b", "gh-pages"], check=True)
        subprocess.run(git + ["add", "-A"], check=True)
        subprocess.run(git + ["commit", "-q", "-m", f"Data {data['updated']}"], check=True)
        subprocess.run(git + ["push", "-q", "-f", REMOTE, "gh-pages"], check=True, capture_output=True)


def main():
    data = fetch()
    (ROOT / "data.json").write_text(json.dumps(data, separators=(",", ":")))
    if "--local" not in sys.argv:
        publish(data)
    print(data["updated"], len(data["now"]), "values")


main()
