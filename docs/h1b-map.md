# H-1B Visa-Approvals Map

**Namespace(s):** `h1b.maps`, `h1b.workflows` ·
**FFL:** `src/h1b/ffl/h1b.ffl` ·
**Handler:** `src/h1b/handlers/h1b_handlers.py` (`handle_build_h1b_map`) ·
**Library:** `src/h1b/_lib.py` (`build_h1b_map`) ·
**Tests:** `tests/test_h1b.py`

## Overview

The flagship (and only) capability of this domain: a single MapLibre choropleth of
**US H-1B visa approvals by state and county**, with a **fiscal-year dropdown**
(FY2009–FY2023) and a **state / county level toggle**. It answers "where do H-1B
petitions get approved, and how has that shifted year over year?" from the public
USCIS H-1B Employer Data Hub.

It is a source→aggregate→join→render pipeline collapsed into one event facet
(`BuildH1bMap`) and one thin workflow (`BuildH1bVisaMap`). This spec is the
end-to-end narrative; the four sub-features each have their own spec
([data-ingest](data-ingest.md), [zip-county-join](zip-county-join.md),
[visualization](visualization.md), [storage](storage.md)).

## How it works

Everything runs inside `_lib.build_h1b_map(force=…)`:

1. **Aggregate** — `download_h1b(force)` fetches each fiscal year's USCIS CSV and
   accumulates approvals two ways: `by_state[name][fy]` and `by_county[geoid][fy]`
   (see [data-ingest](data-ingest.md)). Result is one small
   `h1b-aggregate.json` blob `{"years": [...], "state": {...}, "county": {...}}`.
2. **Assemble geometry** — `assemble_counties()` reads every census-us per-state
   `metrics.geojson` from the shared cache → county records (geometry + population +
   GEOID + state name). If none are present it raises
   `RuntimeError("no county geometry in the census-us cache … run a census map
   first")` — this domain **reuses census-us geometry, it does not fetch TIGER
   itself**.
3. **Build county features** — each county geometry is `shapely` `simplify`d
   (tolerance `COUNTY_SIMPLIFY = 0.01`) and gets a `y_<year>` property per year
   from the county aggregate (`yprops`).
4. **Dissolve to state features** — county geometries are grouped by state,
   `unary_union`-dissolved into a state polygon (`STATE_SIMPLIFY = 0.02`), and given
   `y_<year>` from the by-**state** aggregate (not a sum of counties — the state
   field is authoritative).
5. **Render** — `_render_html(state_fc, county_fc, years)` emits a self-contained
   MapLibre page (see [visualization](visualization.md)).
6. **Write** — `index.html` + `counties.geojson` to `storage.output_root()`.

Data shape: `USCIS CSV → per-year aggregate JSON → two GeoJSON FeatureCollections
(state + county) → one HTML map`.

## Fan-out

**Single-task — no fan-out.** There is no `foreach` in the FFL and no fleet
distribution: `BuildH1bMap` is one atomic multi-year build. All 15 fiscal years are
fetched and both aggregation levels rendered in a single task, because the output is
one combined map with every year attached to every feature (the year dropdown reads
`y_<year>` client-side). The handler registers with `timeout_ms=0` and the domain
raises the task/stuck timeouts to 30/35 min (`__init__.py runner_env`) precisely
because this single blocking task does 15 CSV fetches + the ZIP spatial join on the
first (uncached) run.

## Data & fields

- **Input:** USCIS employer rows keyed on `State` (2-letter) and `ZIP` (first 5),
  approvals summed from `Initial Approval(s)` + `Continuing Approval(s)`.
- **Join key:** county `GEOID` (via ZIP→GEOID, see
  [zip-county-join](zip-county-join.md)); state by full name via `STATE_ABBR`.
- **Geometry:** census-us county features (`GEOID`, `NAME`, `STATEFP`,
  `population`/`B01003_001E`, geometry).
- **Output feature props:** `NAME`, `state` (county level only), and one
  `y_<year>` integer per fiscal year.

## External libraries / binaries

- **`requests`** (pip) — USCIS CSV + ZIP-centroid HTTP fetches.
- **`shapely>=2.0`** (pip) — geometry `shape`/`mapping`, `simplify`, `unary_union`
  dissolve, `STRtree` + `covers` point-in-polygon (in the ZIP join).
- **`boto3`** (pip, fleet only) — lists census-us state prefixes in MinIO
  (`_list_census_states`).
- **MapLibre GL JS 4.7.1** — client-side only, loaded from `unpkg.com` CDN by the
  rendered HTML; not a Python dependency.

## Facets & workflows

| Facet / Workflow | Kind | Effect / Cost / Timeout | Purpose (from FFL docstring) |
|---|---|---|---|
| `h1b.maps.BuildH1bMap(force: Boolean = false) => (html_path, years: Int, county_count: Int, state_count: Int)` | **event** | `Effect(kind="external")` · `Cost(tier="expensive")` · `Timeout(minutes=30)` | "Aggregate USCIS H-1B approvals (FY2009-2023) by state + county and render a year-dropdown / state-county-toggle choropleth. Reuses the census-us cached county geometry. `force` re-fetches the USCIS CSVs." |
| `h1b.workflows.BuildH1bVisaMap(force: Boolean = false) => (status, html_path, years: Int, county_count: Int)` | workflow | — | "Build the US H-1B visa-approvals map (by state & county, multi-year)." Single `andThen` step calling `BuildH1bMap`, then `yield`s `status="completed"` + the map outputs. |

`BuildH1bMap` is the one event facet; its handler (`handle_build_h1b_map`) is a thin
wrapper that calls `build_h1b_map` and re-raises on failure after a `step_log` error
line. Registered via `register_handlers` (RegistryRunner) / `register_poller`
(AgentPoller) with `timeout_ms=0`. The domain surfaces through the
`facetwork.domains` entry point `h1b = "h1b:domain"` (`DomainPackage` in
`__init__.py`).

## Cache / output

- **Cache** (`storage.cache_root()`): `h1b-aggregate.json` (per-year state/county
  aggregate) and `zip-to-geoid.json` (the ZIP→GEOID map). On the fleet these live
  under `s3://afl-cache/cache/h1b/cache/`; locally under `<FW_DATA_ROOT>/h1b-cache/`.
- **Output** (`storage.output_root()`): `index.html` (the map) + `counties.geojson`
  (the simplified county FeatureCollection). Fleet → `s3://afl-cache/cache/h1b/output/`;
  local → `<FW_DATA_ROOT>/h1b-output/`. See [storage](storage.md).
- Result reuse is coarse: `download_h1b` and `_zip_to_geoid` short-circuit on the
  cached JSON (unless `force=True`); `build_h1b_map` itself always re-renders.

## Gotchas & notes

- **Requires a census map first.** `assemble_counties()` reads census-us
  `metrics.geojson` from the *shared* cache; with none present the build errors out.
  This is a hard dependency, not a fallback.
- **`force` only re-fetches the USCIS CSVs**, not the ZIP→GEOID map — `_zip_to_geoid`
  has no `force` path and reuses `zip-to-geoid.json` whenever it exists.
- **Employer address, not worksite.** USCIS reports the petitioning employer's
  registered address; every state/county figure reflects employer location, not
  where the worker actually works. Surfaced in the map's "About this data" modal and
  the README caveat.
- **This is the *approvals* hub, not DOL LCA data.** `_lib`'s docstring is explicit:
  do not swap in the DOL LCA disclosure feed (certified positions ≫ real visas).

## Related specs

- [data-ingest](data-ingest.md) — the USCIS CSV fetch + state/county aggregation
  (the column-rename handling).
- [zip-county-join](zip-county-join.md) — ZIP-centroid → county GEOID spatial join
  and the census-geometry reuse.
- [visualization](visualization.md) — the MapLibre year-dropdown / level-toggle
  choropleth renderer.
- [storage](storage.md) — backend-aware cache + output paths (local vs MinIO/S3).
