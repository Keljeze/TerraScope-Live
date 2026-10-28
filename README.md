# TerraScope Care Resilience — live

Prototype of TerraScope Intelligence on the 277 registered care homes in
Lincolnshire, with a live feed. Every 15 minutes a scheduled GitHub job:

1. fetches Environment Agency flood warnings and alerts near the estate,
2. matches each warning area to the care homes inside it,
3. fetches UKHSA heat and cold weather-health alerts for the homes' regions,
4. republishes the site with a fresh `live/status.json`.

The web app reads that file when it opens and re-checks every 5 minutes.

## What is live and what is not

| Data | Refresh | Source |
|---|---|---|
| Flood warnings and alerts, matched to homes | Every 15 minutes | Environment Agency real-time flood monitoring API |
| Heat-Health and Cold-Health alerts | Every 15 minutes | UKHSA weather-health alerts |
| Care homes | Monthly (manual rebuild) | CQC care directory |
| Flood risk bands | When the Environment Agency republishes | NaFRA2 files, joined with `join_flood.py` |
| Heat and frost averages | Fixed | Met Office HadUK-Grid 1991–2020 |
| Readiness answers, actions, drills | Stored in each viewer's browser | Not shared yet (needs a database: pilot release) |

A source that fails is shown as **unavailable**, never as "no warnings" or "Green".

## Set up (once, about 5 minutes)

1. **Create the repository.** On GitHub: **New repository**, name it `terrascope-live`,
   set it to **Public** (free GitHub Pages needs a public repository), and create it
   empty.
2. **Upload the files.** Click **uploading an existing file** and drag in everything from
   this folder: `index.html`, `README.md`, `.gitignore`, and the `data`, `scripts` and
   `tests` folders. Commit.
3. **Add the workflow file.** Folders starting with a dot are often hidden and skipped
   when dragging, so create this one by hand: **Add file → Create new file**, type the
   name `.github/workflows/live.yml` (the slashes create the folders), paste in the
   contents of `live.yml`, and commit.
4. **Switch Pages to GitHub Actions.** **Settings → Pages → Build and deployment →
   Source: GitHub Actions**.
5. **Run it.** **Actions** tab → **Live feed** → **Run workflow**. When it shows a green
   tick (1–2 minutes), the site is at `https://<your-username>.github.io/terrascope-live/`.

After that it runs by itself every 15 minutes.

## Things to know

- **Timing.** GitHub can start scheduled runs a few minutes late. The page shows when the
  feed was last checked and flags it if that is more than 90 minutes old.
- **60-day pause.** GitHub pauses scheduled jobs in a public repository after 60 days with
  no commits. If that happens, the Actions tab shows an **Enable workflow** button.
- **UKHSA feed.** The alerts come from the feed behind the UKHSA data dashboard. It is not a
  documented public API, so it could change without notice; the page would then show the
  alerts as unavailable.
- **Matching.** A home is matched to a warning when its CQC address point lies inside the
  warning area. Warning areas are drawn by the Environment Agency; this is screening, not a
  statement that a building will flood.
- **Alert regions.** Most homes are in the East Midlands. Homes in postcode districts
  DN31–DN41 use Yorkshire and The Humber; PE1–PE5, PE7 and PE8 use East of England.

## Test without the internet

```
python3 tests/make_mock.py /tmp/mock data/sites.json
python3 scripts/fetch_live.py --sites data/sites.json --out site/live/status.json --cache /tmp/poly --mock /tmp/mock
```

The sample data contains a Flood warning drawn around Skegness (13 homes), a Flood alert
away from any home, a warning no longer in force, and one alert region with no response,
so every path is exercised.

## Attribution

This uses Environment Agency flood and river level data from the real-time data API (Beta).
Weather-health alerts from the UK Health Security Agency. Care home data from the Care
Quality Commission. Climate data from the Met Office. All under the Open Government
Licence v3.0. No personal data is held.
