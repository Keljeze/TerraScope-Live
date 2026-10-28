"""Build sample API responses (documented formats) for an offline test of fetch_live.py."""
import hashlib, json, sys
from pathlib import Path
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
EA = "https://environment.data.gov.uk/flood-monitoring"; UK = "https://ukhsa-dashboard.data.gov.uk/api/proxy/alerts/v1"
def put(url, obj): (out / f"{hashlib.sha1(url.split('?')[0].encode()).hexdigest()[:12]}.json").write_text(json.dumps(obj))
sites = json.load(open(sys.argv[2]))["sites"]
sk = [s for s in sites if s["town"] == "Skegness"]
lo, la = [s["lon"] for s in sk], [s["lat"] for s in sk]
box = [[min(lo)-.005, min(la)-.005], [max(lo)+.005, min(la)-.005], [max(lo)+.005, max(la)+.005], [min(lo)-.005, max(la)+.005], [min(lo)-.005, min(la)-.005]]
put(f"{EA}/id/floods", {"items": [
  {"floodAreaID": "053FWFSKEG01", "description": "Skegness seafront and town centre", "eaAreaName": "Lincolnshire and Northamptonshire",
   "severity": "Flood warning", "severityLevel": 2, "message": "<p>High tides and strong winds. Flooding is expected.</p>",
   "timeRaised": "2026-10-28T05:12:00", "timeMessageChanged": "2026-10-28T06:00:00",
   "floodArea": {"county": "Lincolnshire", "notation": "053FWFSKEG01", "polygon": f"{EA}/id/floodAreas/053FWFSKEG01/polygon", "riverOrSea": "North Sea"}},
  {"floodAreaID": "053WAF999", "description": "Upper River Witham (test area away from homes)", "eaAreaName": "Lincolnshire and Northamptonshire",
   "severity": "Flood alert", "severityLevel": 3, "message": "Flooding is possible.", "timeRaised": "2026-10-28T04:00:00",
   "floodArea": {"county": "Lincolnshire", "notation": "053WAF999", "polygon": f"{EA}/id/floodAreas/053WAF999/polygon", "riverOrSea": "River Witham"}},
  {"floodAreaID": "053OLD", "description": "Old warning", "severity": "Warning no longer in force", "severityLevel": 4, "floodArea": {}}]})
put(f"{EA}/id/floodAreas/053FWFSKEG01/polygon", {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [box]}}]})
put(f"{EA}/id/floodAreas/053WAF999/polygon", {"type": "FeatureCollection", "features": [{"type": "Feature", "geometry": {"type": "MultiPolygon", "coordinates": [[[[0.9,53.9],[1.0,53.9],[1.0,54.0],[0.9,53.9]]]]}}]})
g = lambda s: {"status": s, "risk_score": 1, "text": "<p>Little impact observed on health, healthcare services and social care provision. Business as usual.</p>", "likelihood": "Very low", "impact": "Very low", "geography_name": "East Midlands", "geography_code": "E12000004"}
put(f"{UK}/heat/E12000004", g("Green")); put(f"{UK}/cold/E12000004", dict(g("Yellow"), likelihood="Medium", impact="Low", text="<p>Minor impacts possible across health and social care.</p>"))
put(f"{UK}/heat/E12000006", dict(g("Green"), geography_name="East of England")); put(f"{UK}/cold/E12000006", dict(g("Green"), geography_name="East of England"))
put(f"{UK}/heat/E12000003", dict(g("Green"), geography_name="Yorkshire and The Humber"))   # cold E12000003 left missing: tests the failure path
print("mock written; Skegness homes:", len(sk))
