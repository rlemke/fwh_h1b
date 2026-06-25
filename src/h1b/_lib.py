"""H-1B visa approvals by US state & county, multi-year.

Source: the **USCIS H-1B Employer Data Hub** per-fiscal-year CSVs (actual approved
petitions — Initial + Continuing — by employer, with State / City / ZIP). NOT the
DOL LCA disclosure data (those are *certified positions* / applications, far more
numerous than real visas).

Pipeline (all backend-aware via :mod:`h1b.storage`):

1. ``download_h1b`` — fetch each fiscal year's USCIS CSV and aggregate approvals
   two ways: by **state** (the 2-letter State field → state name) and by **county**
   (employer **ZIP → county GEOID** via a ZIP-centroid point-in-polygon against the
   census county polygons). Cached as one small per-year aggregate JSON.
2. ``build_h1b_map`` — assemble county geometry + population from the census-us
   cache (shared MinIO), attach each year's approvals to every state/county
   feature, dissolve counties → state polygons, simplify, and render a MapLibre
   choropleth with a **year dropdown** + a **state/county level toggle**.

Caveat: USCIS reports the *employer's petition address*, not the worker's actual
worksite — so county/state reflect where the petitioning employer is registered.
"""

from __future__ import annotations

import csv
import io
import json
import logging
import time
from collections import defaultdict
from dataclasses import dataclass

from . import storage as cstore

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

logger = logging.getLogger("h1b")
csv.field_size_limit(20_000_000)

USER_AGENT = "Mozilla/5.0 (facetwork-h1b/1.0; +https://github.com/rlemke/facetwork)"
USCIS_CSV = "https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-{y}.csv"
YEARS = list(range(2009, 2024))  # FY2009–FY2023 available on the data hub
ZIP_CENTROIDS_URL = "https://raw.githubusercontent.com/midwire/free_zipcode_data/master/all_us_zipcodes.csv"
CENSUS_METRICS_PREFIX = "cache/census-us/output/metrics"
FFL_URL = "https://github.com/rlemke/fwh_h1b/blob/main/src/h1b/ffl/h1b.ffl"

COUNTY_SIMPLIFY = 0.01
STATE_SIMPLIFY = 0.02

# Sequential YlOrRd: more H-1B = darker.
RAMP = [
    [0.0, "#ffffb2"], [0.25, "#fecc5c"], [0.5, "#fd8d3c"],
    [0.75, "#f03b20"], [1.0, "#bd0026"],
]
NODATA = "#e0e0e0"
OUTLIER = "#5e3c99"  # distinct colour for the high tail above the p90 cap

STATE_ABBR = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas", "CA": "California",
    "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware", "DC": "District of Columbia",
    "FL": "Florida", "GA": "Georgia", "HI": "Hawaii", "ID": "Idaho", "IL": "Illinois",
    "IN": "Indiana", "IA": "Iowa", "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana",
    "ME": "Maine", "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan",
    "MN": "Minnesota", "MS": "Mississippi", "MO": "Missouri", "MT": "Montana",
    "NE": "Nebraska", "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey",
    "NM": "New Mexico", "NY": "New York", "NC": "North Carolina", "ND": "North Dakota",
    "OH": "Ohio", "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania",
    "RI": "Rhode Island", "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee",
    "TX": "Texas", "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


@dataclass
class H1bMapResult:
    output_path: str
    html_path: str
    years: int
    county_count: int
    state_count: int


def _num(x) -> int:
    try:
        return int(str(x).replace(",", "").strip() or 0)
    except ValueError:
        return 0


def _col(row: dict, *names: str):
    """First present column among ``names`` — USCIS renamed the approval columns
    over the years (FY2009-2019 use the plural 'Initial Approvals', FY2021+ use
    the singular 'Initial Approval')."""
    for n in names:
        if n in row:
            return row[n]
    return None


def _approvals(row: dict) -> int:
    return (_num(_col(row, "Initial Approval", "Initial Approvals"))
            + _num(_col(row, "Continuing Approval", "Continuing Approvals")))


# ---------------------------------------------------------------------------
# Aggregate H-1B approvals by state + county across fiscal years.
# ---------------------------------------------------------------------------


def download_h1b(*, force: bool = False) -> dict:
    """Return ``{"years": [...], "state": {name: {fy: n}}, "county": {geoid: {fy: n}}}``,
    cached as JSON."""
    cache_key = cstore.join(cstore.cache_root(), "h1b-aggregate.json")
    if not force and cstore.exists(cache_key):
        with cstore.open_read(cache_key) as f:
            return json.load(f)
    if requests is None:
        raise RuntimeError("requests is required to download the USCIS data")

    zip2geoid = _zip_to_geoid()
    by_state: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    by_county: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    years = []
    for y in YEARS:
        url = USCIS_CSV.format(y=y)
        try:
            r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=120)
            if r.status_code != 200:
                logger.warning("FY%s: HTTP %s, skipping", y, r.status_code)
                continue
        except Exception as exc:
            logger.warning("FY%s fetch failed: %s", y, exc)
            continue
        rows = list(csv.DictReader(io.StringIO(r.text)))
        if not rows:
            continue
        years.append(y)
        fy = str(y)
        for row in rows:
            appr = _approvals(row)
            if appr <= 0:
                continue
            st = (row.get("State") or "").strip().upper()
            name = STATE_ABBR.get(st)
            if name:
                by_state[name][fy] += appr
            zc = (row.get("ZIP") or "").strip()[:5]
            geoid = zip2geoid.get(zc)
            if geoid:
                by_county[geoid][fy] += appr
        logger.info("FY%s aggregated (%d employer rows)", y, len(rows))

    blob = {"years": years, "state": by_state, "county": by_county}
    with cstore.open_write(cache_key, "w") as f:
        json.dump(blob, f)
    logger.info("H-1B aggregate: %d years, %d states, %d counties",
                len(years), len(by_state), len(by_county))
    return blob


# ---------------------------------------------------------------------------
# ZIP → county GEOID (centroid point-in-polygon against census counties).
# ---------------------------------------------------------------------------


def _zip_to_geoid() -> dict[str, str]:
    """Build (and cache) ``{zip5: county_geoid}`` by spatial-joining ZIP centroids
    onto the census county polygons."""
    cache_key = cstore.join(cstore.cache_root(), "zip-to-geoid.json")
    if cstore.exists(cache_key):
        with cstore.open_read(cache_key) as f:
            return json.load(f)
    from shapely.geometry import shape, Point
    from shapely.strtree import STRtree

    counties = assemble_counties()
    geoms = [shape(c["geometry"]) for c in counties]
    tree = STRtree(geoms)

    r = requests.get(ZIP_CENTROIDS_URL, headers={"User-Agent": USER_AGENT}, timeout=120)
    r.raise_for_status()
    z2g: dict[str, str] = {}
    t0 = time.time()
    for row in csv.DictReader(io.StringIO(r.text)):
        z = (row.get("code") or row.get("zip") or row.get("zipcode") or "").strip()[:5]
        try:
            lon, lat = float(row["lon"]), float(row["lat"])
        except (KeyError, ValueError, TypeError):
            continue
        if not z:
            continue
        pt = Point(lon, lat)
        for i in tree.query(pt):
            if geoms[i].covers(pt):
                z2g[z] = counties[i]["geoid"]
                break
    logger.info("ZIP→county: %d ZIPs mapped in %.1fs", len(z2g), time.time() - t0)
    with cstore.open_write(cache_key, "w") as f:
        json.dump(z2g, f)
    return z2g


def assemble_counties() -> list[dict]:
    """Read every census-us per-state county GeoJSON → county records
    (geometry + population + GEOID + state name)."""
    counties: list[dict] = []
    for state in _list_census_states():
        path = _census_metrics_path(state)
        if not cstore.exists(path):
            continue
        with cstore.open_read(path) as f:
            fc = json.load(f)
        for ft in fc.get("features") or []:
            p = ft.get("properties") or {}
            pop = p.get("population") or p.get("B01003_001E")
            counties.append({
                "geoid": p.get("GEOID"), "name": p.get("NAME"), "state": state,
                "statefp": p.get("STATEFP"), "pop": float(pop) if pop else None,
                "geometry": ft.get("geometry"),
            })
    return counties


def _list_census_states() -> list[str]:
    import os
    import boto3
    data_root = cstore._data_root()
    if cstore.is_remote(data_root):
        bucket = data_root.split("://", 1)[1].split("/", 1)[0]
        s3 = boto3.client(
            "s3", endpoint_url=os.environ.get("AFL_S3_ENDPOINT"),
            aws_access_key_id=os.environ.get("AFL_S3_ACCESS_KEY"),
            aws_secret_access_key=os.environ.get("AFL_S3_SECRET_KEY"),
        )
        states = set()
        for pg in s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=CENSUS_METRICS_PREFIX + "/"
        ):
            for o in pg.get("Contents", []):
                if o["Key"].endswith("/metrics.geojson"):
                    states.add(o["Key"].split("/")[-2])
        return sorted(states)
    base = cstore.join(data_root, CENSUS_METRICS_PREFIX)
    if os.path.isdir(base):
        return sorted(d for d in os.listdir(base)
                      if os.path.exists(os.path.join(base, d, "metrics.geojson")))
    return []


def _census_metrics_path(state: str) -> str:
    return cstore.join(cstore._data_root(), CENSUS_METRICS_PREFIX, state, "metrics.geojson")


# ---------------------------------------------------------------------------
# Build map.
# ---------------------------------------------------------------------------


def build_h1b_map(*, force: bool = False) -> H1bMapResult:
    from shapely.geometry import shape
    from shapely.ops import unary_union
    import shapely.geometry as sg

    agg = download_h1b(force=force)
    years = agg["years"]
    counties = assemble_counties()
    if not counties:
        raise RuntimeError(
            f"no county geometry in the census-us cache ({CENSUS_METRICS_PREFIX}) — "
            "run a census map first"
        )

    def yprops(per_year: dict[str, int]) -> dict:
        return {f"y_{y}": int(per_year.get(str(y), 0)) for y in years}

    # County features.
    county_feats = []
    state_geoms: dict[str, list] = defaultdict(list)
    for c in counties:
        g = shape(c["geometry"])
        simp = g.simplify(COUNTY_SIMPLIFY, preserve_topology=True)
        props = {"NAME": c["name"], "state": c["state"]}
        props.update(yprops(agg["county"].get(c["geoid"], {})))
        county_feats.append({"type": "Feature", "geometry": sg.mapping(simp), "properties": props})
        if c["state"]:
            state_geoms[c["state"]].append(g)

    # State features (dissolve counties; approvals from the by-state aggregate).
    state_feats = []
    for state, gs in state_geoms.items():
        union = unary_union(gs).simplify(STATE_SIMPLIFY, preserve_topology=True)
        props = {"NAME": state}
        props.update(yprops(agg["state"].get(state, {})))
        state_feats.append({"type": "Feature", "geometry": sg.mapping(union), "properties": props})

    county_fc = {"type": "FeatureCollection", "features": county_feats}
    state_fc = {"type": "FeatureCollection", "features": state_feats}
    html = _render_html(state_fc, county_fc, years)

    out_dir = cstore.output_root()
    html_path = cstore.join(out_dir, "index.html")
    with cstore.open_write(cstore.join(out_dir, "counties.geojson"), "w") as f:
        json.dump(county_fc, f, separators=(",", ":"))
    with cstore.open_write(html_path, "w") as f:
        f.write(html)
    return H1bMapResult(html_path, html_path, len(years), len(county_feats), len(state_feats))


# ---------------------------------------------------------------------------
# Render — year dropdown + state/county toggle choropleth.
# ---------------------------------------------------------------------------


def _attribution() -> str:
    from datetime import UTC, datetime
    from html import escape
    ts = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")
    call = "h1b.workflows.BuildH1bVisaMap"
    repo = FFL_URL.split("/blob/")[0]
    return (
        '<div style="position:fixed;bottom:10px;left:10px;z-index:9999;'
        "background:rgba(255,255,255,0.92);border-radius:6px;padding:6px 10px;"
        "box-shadow:0 1px 4px rgba(0,0,0,0.2);font:11px system-ui,sans-serif;color:#444;"
        'max-width:470px">Generated by Facetwork workflow '
        '<code style="background:#f0f0f0;padding:0 3px;border-radius:3px">'
        f"{escape(call)}</code> &middot; "
        f'<a href="{escape(FFL_URL)}" target="_blank" rel="noopener" '
        'style="color:#1565c0;text-decoration:none">view FFL</a>'
        f' &middot; <a href="{escape(repo)}" target="_blank" rel="noopener" '
        'style="color:#1565c0;text-decoration:none">source repo</a>'
        f" &middot; generated {ts}</div>"
    )


def _render_html(state_fc: dict, county_fc: dict, years: list[int]) -> str:
    state_js = json.dumps(state_fc, separators=(",", ":"))
    county_js = json.dumps(county_fc, separators=(",", ":"))
    ramp_js = json.dumps(RAMP)
    years_js = json.dumps(years)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>H-1B visa approvals by US state &amp; county</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.css" rel="stylesheet">
<script src="https://unpkg.com/maplibre-gl@4.7.1/dist/maplibre-gl.js"></script>
<style>
  html,body,#map{{margin:0;height:100%;width:100%;font-family:system-ui,sans-serif}}
  .panel{{position:absolute;z-index:1;background:rgba(255,255,255,.94);padding:10px 12px;
    border-radius:6px;box-shadow:0 1px 4px rgba(0,0,0,.3);font-size:12px}}
  #ctl{{top:10px;left:10px;max-width:340px}}
  #ctl h3{{margin:0 0 6px;font-size:14px}} #ctl select{{font-size:13px;padding:2px}}
  #legend{{bottom:18px;right:10px}} #legend .scale{{display:flex;margin-top:4px}}
  #legend .scale div{{display:flex;flex-direction:column;align-items:center;font-size:10px}}
  #legend .scale span{{width:34px;height:12px}}
  .maplibregl-popup-content{{max-width:300px;font-size:12px}}
  .maplibregl-popup-content h4{{margin:0 0 4px;font-size:13px}}
  table.m{{border-collapse:collapse;margin-top:4px}} table.m td{{padding:1px 6px 1px 0}}
  table.m td.v{{text-align:right}}
  .rsearch{{position:absolute;top:10px;left:50%;transform:translateX(-50%);z-index:6;width:300px;max-width:70%}}
  .rsearch input{{width:100%;box-sizing:border-box;padding:7px 11px;border:1px solid #aaa;border-radius:6px;font-size:13px;box-shadow:0 2px 6px rgba(0,0,0,.2)}}
  .rsearch .res{{background:#fff;border-radius:0 0 6px 6px;box-shadow:0 2px 6px rgba(0,0,0,.2);max-height:240px;overflow:auto}}
  .rsearch .res div{{padding:6px 11px;cursor:pointer;font-size:12px;border-top:1px solid #f0f0f0}}
  .rsearch .res div:hover{{background:#f3f3f3}}
</style></head>
<body>
<div id="map"></div>
<div class="rsearch"><input id="rsin" placeholder="Find a state or county..." autocomplete="off"><div class="res" id="rsres"></div></div>
<div id="ctl" class="panel">
  <h3>H-1B visa approvals &middot; US</h3>
  <div>Fiscal year <select id="year"></select></div>
  <div style="margin-top:4px"><label><input type="radio" name="lvl" value="state" checked> By state</label>
  &nbsp; <label><input type="radio" name="lvl" value="county"> By county</label></div>
  <div style="margin-top:5px;color:#555">USCIS H-1B approved petitions (Initial +
  Continuing) by employer location, per fiscal year. Darker = more approvals; scale
  clamped at the 90th percentile, high outliers in <b style="color:#5e3c99">purple</b>.
  Click an area for its count. <b>Note:</b> location is the petitioning employer's
  address, not the worker's worksite. Source: USCIS H-1B Employer Data Hub; geometry
  from US Census TIGER.</div>
</div>
<div id="legend" class="panel"><b id="lgttl"></b><div class="scale" id="lgscale"></div></div>
{_attribution()}
<script>
const STATE={state_js}, COUNTY={county_js}, RAMP={ramp_js}, YEARS={years_js};
let year=YEARS[YEARS.length-1], level='state';
const KEY=()=>'y_'+year;
const fmtn=v=>(v===null||v===undefined||v==='')?'0':Math.round(v).toLocaleString();
function vals(fc){{const k=KEY();return fc.features.map(f=>f.properties[k]).filter(v=>typeof v==='number'&&v>0);}}
function quantile(s,q){{const i=(s.length-1)*q,lo=Math.floor(i),hi=Math.ceil(i);return lo===hi?s[lo]:s[lo]+(s[hi]-s[lo])*(i-lo);}}
function bounds(fc){{const a=vals(fc).slice().sort((x,y)=>x-y);if(!a.length)return null;let lo=a[0],hi=quantile(a,0.90);if(lo>=hi)hi=lo+1;return [lo,hi];}}
function activeFc(){{return level==='state'?STATE:COUNTY;}}
function colorExpr(){{
  const fc=activeFc(),b=bounds(fc); if(!b) return '{NODATA}'; const lo=b[0],hi=b[1],k=KEY();
  const expr=['interpolate',['linear'],['get',k]];
  RAMP.forEach(r=>expr.push(lo+(hi-lo)*r[0],r[1]));  // high = dark
  return ['case',['==',['get',k],null],'{NODATA}',['<=',['get',k],0],'{NODATA}',['>',['get',k],hi],'{OUTLIER}',expr];
}}
function legend(){{
  const fc=activeFc(),b=bounds(fc),sc=document.getElementById('lgscale');sc.innerHTML='';
  document.getElementById('lgttl').textContent='H-1B approvals '+year+(level==='county'?' (county)':' (state)');
  if(!b)return;const lo=b[0],hi=b[1];
  RAMP.forEach(r=>{{const d=document.createElement('div');d.innerHTML=`<span style="background:${{r[1]}}"></span>${{fmtn(lo+(hi-lo)*r[0])}}`;sc.appendChild(d);}});
  const o=document.createElement('div');o.innerHTML=`<span style="background:{OUTLIER}"></span>${{'>'+fmtn(hi)}}`;sc.appendChild(o);
}}
const map=new maplibregl.Map({{container:'map',style:{{version:8,
  sources:{{bm:{{type:'raster',tiles:['https://a.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}.png','https://b.basemaps.cartocdn.com/rastertiles/voyager/{{z}}/{{x}}/{{y}}.png'],tileSize:256,attribution:'&copy; OpenStreetMap &copy; CARTO &middot; USCIS'}}}},
  layers:[{{id:'bm',type:'raster',source:'bm'}}]}},center:[-96,38],zoom:3.4}});
map.addControl(new maplibregl.NavigationControl());
const ysel=document.getElementById('year');
YEARS.forEach(y=>{{const o=document.createElement('option');o.value=y;o.textContent='FY'+y;ysel.appendChild(o);}});
ysel.value=year;
function refresh(){{map.setPaintProperty('fill','fill-color',colorExpr());legend();}}
function popup(e){{const p=e.features[0].properties||{{}};
  let rows='';YEARS.slice().reverse().forEach(y=>{{const sel=(y==year)?' style="font-weight:700"':'';
    rows+=`<tr${{sel}}><td>FY${{y}}</td><td class="v">${{fmtn(p['y_'+y])}}</td></tr>`;}});
  new maplibregl.Popup({{closeButton:true,maxWidth:'260px'}}).setLngLat(e.lngLat)
    .setHTML(`<h4>${{p.NAME||''}}</h4><table class="m">${{rows}}</table>`).addTo(map);}}
map.on('load',()=>{{
  map.addSource('d',{{type:'geojson',data:STATE}});
  map.addLayer({{id:'fill',type:'fill',source:'d',paint:{{'fill-color':colorExpr(),'fill-opacity':0.82}}}});
  map.addLayer({{id:'line',type:'line',source:'d',paint:{{'line-color':'#888','line-width':0.3}}}});
  legend();
  map.on('click','fill',popup);
  map.on('mouseenter','fill',()=>map.getCanvas().style.cursor='pointer');
  map.on('mouseleave','fill',()=>map.getCanvas().style.cursor='');
  ysel.addEventListener('change',()=>{{year=+ysel.value;refresh();}});
  document.querySelectorAll('input[name=lvl]').forEach(r=>r.addEventListener('change',()=>{{
    level=document.querySelector('input[name=lvl]:checked').value;
    map.getSource('d').setData(activeFc());
    map.setPaintProperty('line','line-width',level==='county'?0.15:0.3);
    refresh();
  }}));
  const inp=document.getElementById('rsin'),res=document.getElementById('rsres');
  function bbox(g){{let a=[180,90,-180,-90];const w=c=>{{if(typeof c[0]==='number'){{a[0]=Math.min(a[0],c[0]);a[1]=Math.min(a[1],c[1]);a[2]=Math.max(a[2],c[0]);a[3]=Math.max(a[3],c[1]);}}else c.forEach(w);}};w(g.coordinates);return a;}}
  inp.addEventListener('input',()=>{{const q=inp.value.trim().toLowerCase();res.innerHTML='';if(q.length<2)return;
    activeFc().features.map(f=>({{n:f.properties.NAME||'',f}})).filter(x=>x.n.toLowerCase().includes(q)).slice(0,12).forEach(x=>{{
      const d=document.createElement('div');d.textContent=x.n;
      d.addEventListener('click',()=>{{const b=bbox(x.f.geometry);
        map.fitBounds([[b[0],b[1]],[b[2],b[3]]],{{padding:40,maxZoom:9,duration:700}});res.innerHTML='';inp.value=x.n;}});
      res.appendChild(d);}});}});
  document.addEventListener('click',e=>{{if(!e.target.closest('.rsearch'))res.innerHTML='';}});
}});
</script></body></html>"""
