# Home dashboard

Static HTML dashboard of our Home Assistant sensors (indoor/outdoor climate, attic,
ventilation, heating power), published on GitHub Pages.

`update.py` runs every 15 minutes on the home Mac (launchd). It reads the current
values and 48 h of history from Home Assistant over the LAN, writes `data.json`,
and force-pushes `index.html` + `data.json` as a single commit to the `gh-pages`
branch. Only the entities listed in `ENTITIES` are published. The HA token stays
on the Mac (`~/.config/homeassistant/token`).

```bash
python3 update.py --local                  # fetch only, then open index.html via a local server
python3 -m http.server 8765                # http://127.0.0.1:8765/
launchctl kickstart -k gui/$(id -u)/com.veikkosalminen.home-dashboard   # run the job now
```

Install the job:

```bash
cp com.veikkosalminen.home-dashboard.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.veikkosalminen.home-dashboard.plist
```
