# ZIP → County Spatial Join (census-geometry reuse)

**Namespace(s):** `h1b.maps` (backing library) ·
**Library:** `src/h1b/_lib.py`
(`_zip_to_geoid`, `assemble_counties`, `_list_census_states`, `_census_metrics_path`) ·
**Storage:** `src/h1b/storage.py`

## Overview

USCIS gives an employer **ZIP**, not a county. This feature turns each ZIP into a
county **GEOID** by spatially joining ZIP centroids onto census county polygons,
and — separately — assembles those same census polygons into the geometry the map
renders. It is the reason the domain needs **no TIGER download of its own**: it
piggybacks entirely on the shared census-us county cache.

## How it works

Two cooperating functions:

**`assemble_counties()`** — reads every census-us per-state `metrics.geojson` from
the shared cache and flattens each feature to a record:
`{geoid: GEOID, name: NAME, state, statefp: STATEFP, pop: population|B01003_001E,
geometry}`. State discovery is backend-aware via `_list_census_states()`:

- **Remote (S3/MinIO):** `boto3` paginates `list_objects_v2` under
  `CENSUS_METRICS_PREFIX = "cache/census-us/output/metrics"` and collects each
  `.../<state>/metrics.geojson` prefix.
- **Local:** lists subdirs of `<FW_DATA_ROOT>/cache/census-us/output/metrics`
  containing a `metrics.geojson`.

**`_zip_to_geoid()`** — builds (and caches) `{zip5: county_geoid}`:

1. `assemble_counties()` → shapely `shape()` per county → `STRtree(geoms)` spatial
   index.
2. GET the ZIP-centroid CSV
   (`ZIP_CENTROIDS_URL`, the midwire `free_zipcode_data` `all_us_zipcodes.csv`).
3. For each ZIP: read `code`/`zip`/`zipcode` + `lon`/`lat`, form a `Point`, query
   the STRtree for candidate polygons, and assign the first county whose polygon
   `covers(pt)`.
4. Persist to `zip-to-geoid.json`.

Data shape: `census county GeoJSON + ZIP-centroid CSV → STRtree point-in-polygon →
{zip5: geoid} JSON`.

## Fan-out

**Single-task — no fan-out.** The STRtree join over all US ZIPs runs once inside
`BuildH1bMap` (and is cached thereafter). It is a notable slice of first-run
wall-clock, logged as `"ZIP→county: %d ZIPs mapped in %.1fs"`.

## Data & fields

- **Census county** (from `metrics.geojson`): `GEOID` (the join target), `NAME`,
  `STATEFP`, `population` or `B01003_001E`, and the polygon `geometry`.
- **ZIP centroids** (midwire CSV): `code`/`zip`/`zipcode` (first 5 chars) and
  `lon`/`lat` (floats; rows missing/invalid coords are skipped).
- **Join mechanism:** `shapely.strtree.STRtree` bbox query + `geom.covers(Point)`
  exact test — a centroid point-in-polygon, first match wins.

## External libraries / binaries

- **`shapely>=2.0`** (pip) — `geometry.shape`, `geometry.Point`, `strtree.STRtree`,
  `covers`. Imported lazily inside the functions.
- **`requests`** (pip) — the ZIP-centroid CSV fetch.
- **`boto3`** (pip, fleet only) — S3 listing of census state prefixes in
  `_list_census_states`.

## Facets & workflows

No dedicated facet — both functions are internal steps of `h1b.maps.BuildH1bMap`
(see [h1b-map](h1b-map.md)). `assemble_counties` is called from both
`_zip_to_geoid` (for the join geometry) and `build_h1b_map` (for the map geometry).

## Cache / output

- **`zip-to-geoid.json`** under `storage.cache_root()` — the persisted ZIP→GEOID
  map. Fleet: `s3://afl-cache/cache/h1b/cache/`; local: `<FW_DATA_ROOT>/h1b-cache/`.
- **Input geometry is not re-cached** — it is read live from the census-us cache
  (`cache/census-us/output/metrics/<state>/metrics.geojson`) each build.

## Gotchas & notes

- **Hard dependency on the census-us cache.** No census `metrics.geojson` → empty
  county list → `assemble_counties()` yields nothing → `build_h1b_map` raises
  `"no county geometry in the census-us cache … run a census map first"`. Run a
  census map on the same shared MinIO first.
- **Centroid join, not areal.** A ZIP is assigned to the single county containing
  its centroid; multi-county ZIPs collapse to one county. This is a deliberate
  simplification for choropleth colouring.
- **No `force` path.** `_zip_to_geoid` reuses `zip-to-geoid.json` whenever present;
  a census-geometry refresh that changes county polygons will **not** be picked up
  until that cache file is deleted.
- **GEOID must match** between the ZIP-join geometry and the map geometry — both come
  from the same `assemble_counties()` output, so they are consistent by construction.

## Related specs

- [data-ingest](data-ingest.md) — the consumer of `zip-to-geoid.json` (county
  aggregation).
- [h1b-map](h1b-map.md) — the facet driving the join; also dissolves these counties
  into state polygons.
- [storage](storage.md) — the cache/S3 plumbing these functions use.
