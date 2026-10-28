#!/usr/bin/env python3
"""
TerraScope live feed: fetch current flood warnings and weather-health alerts,
match warnings to care homes, and write site/live/status.json for the web app.

Runs on a schedule in GitHub Actions (see .github/workflows/live.yml).
Standard library only, so the job needs no installs.

Sources (Open Government Licence):
  Environment Agency real-time flood monitoring API, updated every 15 minutes
    https://environment.data.gov.uk/flood-monitoring/doc/reference
    Attribution: "this uses Environment Agency flood and river level data from
    the real-time data API (Beta)"
  UKHSA weather-health alerts, the feed behind the UKHSA data dashboard
    https://ukhsa-dashboard.data.gov.uk/weather-health-alerts

Rules this script keeps:
  * A source that fails is recorded as unavailable. It is never reported as
    "no warnings" or "Green" - an outage must not read as all-clear.
  * Flood warnings are issued for warning AREAS, not addresses. A home is
    affected when its CQC address point lies inside the area's polygon.
  * Area polygons are cached between runs (they rarely change).

Usage:
  python3 -I scripts/fetch_live.py --sites data/sites.json --out site/live/status.json --cache .cache/polygons
  python3 -I scripts/fetch_live.py ... --mock tests/mock      # offline test with sample responses
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

EA = "https://environment.data.gov.uk/flood-monitoring"
UKHSA = "https://ukhsa-dashboard.data.gov.uk/api/proxy/alerts/v1"
UA = "TerraScope-live/1.0 (+https://github.com; care home resilience prototype)"

REGIONS = {
    "E12000004": "East Midlands",
    "E12000003": "Yorkshire and The Humber",
    "E12000006": "East of England",
}
SEVERITY = {1: "Severe flood warning", 2: "Flood warning", 3: "Flood alert", 4: "Warning no longer in force"}

MOCK: Path | None = None


def now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()


def region_for(postcode: str) -> str:
    """UKHSA alert region for a home, from its postcode district.

    DN31-DN41 are North and North East Lincolnshire (Yorkshire and The Humber).
    PE1-PE5, PE7, PE8 are Peterborough (East of England). PE6 is split between
    Peterborough villages and the Deepings (Lincolnshire); it is kept in the
    East Midlands, the region for the Deepings. Everything else in this
    dataset is East Midlands."""
    m = re.match(r"^([A-Z]{1,2})(\d{1,2})", (postcode or "").upper().replace(" ", ""))
    if not m:
        return "E12000004"
    area, d = m.group(1), int(m.group(2))
    if area == "DN" and 31 <= d <= 41:
        return "E12000003"
    if area == "PE" and d in (1, 2, 3, 4, 5, 7, 8):
        return "E12000006"
    return "E12000004"


def get_json(url: str, tries: int = 3):
    if MOCK is not None:
        key = hashlib.sha1(url.split("?")[0].encode()).hexdigest()[:12]
        p = MOCK / f"{key}.json"
        if not p.exists():
            raise FileNotFoundError(f"no mock for {url} ({p.name})")
        return json.loads(p.read_text(encoding="utf-8"))
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            last = e
            time.sleep(2 * (i + 1))
    raise RuntimeError(f"{url}: {last}")


def strip_html(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", s or "")).strip()


# ---------------------------------------------------------------- geometry
def haversine_km(lat1, lon1, lat2, lon2) -> float:
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def in_ring(x: float, y: float, ring) -> bool:
    inside = False
    n = len(ring)
    for i in range(n):
        x1, y1 = ring[i][0], ring[i][1]
        x2, y2 = ring[(i + 1) % n][0], ring[(i + 1) % n][1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / ((y2 - y1) or 1e-15) + x1:
            inside = not inside
    return inside


def in_polygon(x, y, rings) -> bool:
    """rings[0] = outer boundary, the rest = holes."""
    return bool(rings) and in_ring(x, y, rings[0]) and not any(in_ring(x, y, h) for h in rings[1:])


def polygons_of(geojson) -> list:
    """All polygons (each a list of rings) in a GeoJSON object."""
    out = []
    def walk(g):
        if not g:
            return
        t = g.get("type")
        if t == "FeatureCollection":
            for f in g.get("features", []):
                walk(f)
        elif t == "Feature":
            walk(g.get("geometry"))
        elif t == "Polygon":
            out.append(g["coordinates"])
        elif t == "MultiPolygon":
            out.extend(g["coordinates"])
        elif t == "GeometryCollection":
            for x in g.get("geometries", []):
                walk(x)
    walk(geojson)
    return out


def bbox(polys):
    xs = [p[0] for poly in polys for p in poly[0]]
    ys = [p[1] for poly in polys for p in poly[0]]
    return min(xs), min(ys), max(xs), max(ys)


# ---------------------------------------------------------------- sources
def fetch_alerts(errors: list) -> dict:
    out = {}
    for code, name in REGIONS.items():
        out[code] = {"region": name}
        for kind in ("heat", "cold"):
            url = f"{UKHSA}/{kind}/{code}"
            try:
                raw = get_json(url)
                out[code][kind] = {
                    "status": raw.get("status") or "Unknown",
                    "likelihood": raw.get("likelihood") or "",
                    "impact": raw.get("impact") or "",
                    "text": strip_html(raw.get("text")),
                    "period_start": raw.get("period_start"),
                    "period_end": raw.get("period_end"),
                    "region": raw.get("geography_name") or name,
                    "retrieved": now_iso(),
                }
            except Exception as e:  # recorded, never silently treated as Green
                out[code][kind] = None
                errors.append({"source": f"UKHSA {kind} {name}", "error": str(e)[:300]})
    return out


def fetch_floods(sites: list, cache: Path, errors: list) -> dict:
    lat0 = sum(s["lat"] for s in sites) / len(sites)
    lon0 = sum(s["lon"] for s in sites) / len(sites)
    radius = max(haversine_km(lat0, lon0, s["lat"], s["lon"]) for s in sites) + 15
    url = f"{EA}/id/floods?lat={lat0:.4f}&long={lon0:.4f}&dist={radius:.0f}"
    try:
        items = get_json(url).get("items", [])
    except Exception as e:
        errors.append({"source": "Environment Agency flood warnings", "error": str(e)[:300]})
        return {"ok": False, "warnings": [], "searched_km": round(radius)}

    cache.mkdir(parents=True, exist_ok=True)
    warnings = []
    for it in items:
        level = int(it.get("severityLevel") or 0)
        if level not in (1, 2, 3):           # 4 = no longer in force
            continue
        area = it.get("floodArea") or {}
        area_id = it.get("floodAreaID") or area.get("notation") or ""
        poly_url = area.get("polygon") or (f"{EA}/id/floodAreas/{area_id}/polygon" if area_id else "")
        homes, note = [], ""
        try:
            cp = cache / f"{re.sub(r'[^A-Za-z0-9_-]', '_', area_id)}.json"
            if cp.exists():
                geo = json.loads(cp.read_text(encoding="utf-8"))
            else:
                geo = get_json(poly_url)
                cp.write_text(json.dumps(geo), encoding="utf-8")
            polys = polygons_of(geo)
            if polys and abs(bbox(polys)[0]) > 180:   # projected coordinates, not lon/lat
                raise ValueError("polygon not in WGS84 longitude/latitude")
            x0, y0, x1, y1 = bbox(polys) if polys else (0, 0, 0, 0)
            for s in sites:
                x, y = s["lon"], s["lat"]
                if x0 <= x <= x1 and y0 <= y <= y1 and any(in_polygon(x, y, p) for p in polys):
                    homes.append(s["id"])
        except Exception as e:
            note = "Area boundary unavailable, so homes could not be matched"
            errors.append({"source": f"Flood area polygon {area_id}", "error": str(e)[:300]})
        warnings.append({
            "id": area_id,
            "area": it.get("description") or area.get("description") or area_id,
            "ea_area": it.get("eaAreaName") or "",
            "county": area.get("county") or "",
            "water": area.get("riverOrSea") or "",
            "level": level,
            "severity": SEVERITY.get(level, it.get("severity") or ""),
            "message": strip_html(it.get("message"))[:1200],
            "raised": it.get("timeRaised"),
            "changed": it.get("timeMessageChanged") or it.get("timeSeverityChanged"),
            "homes": homes,
            "note": note,
            "url": f"https://check-for-flooding.service.gov.uk/target-area/{area_id}" if area_id else "",
        })
    warnings.sort(key=lambda w: (w["level"], -len(w["homes"])))
    return {"ok": True, "warnings": warnings, "searched_km": round(radius), "in_force_nearby": len(warnings)}


def main():
    global MOCK
    ap = argparse.ArgumentParser()
    ap.add_argument("--sites", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--cache", type=Path, default=Path(".cache/polygons"))
    ap.add_argument("--mock", type=Path)
    a = ap.parse_args()
    MOCK = a.mock

    sites = [s for s in json.loads(a.sites.read_text(encoding="utf-8"))["sites"] if s.get("lat") is not None]
    errors: list = []
    alerts = fetch_alerts(errors)
    floods = fetch_floods(sites, a.cache, errors)
    home_regions = {s["id"]: region_for(s.get("pc", "")) for s in sites}

    status = {
        "checked": now_iso(),
        "alerts": alerts,
        "home_regions": home_regions,
        "floods": floods,
        "errors": errors,
        "attribution": "This uses Environment Agency flood and river level data from the real-time data API (Beta). "
                       "Weather-health alerts from the UK Health Security Agency. Open Government Licence v3.0.",
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(status, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    hit = sum(len(w["homes"]) for w in floods["warnings"])
    print(f"checked {status['checked']}: {len(floods['warnings'])} warnings in force within "
          f"{floods.get('searched_km')} km, {hit} home matches, {len(errors)} source errors")
    for e in errors:
        print("  error:", e["source"], "-", e["error"], file=sys.stderr)


if __name__ == "__main__":
    main()
