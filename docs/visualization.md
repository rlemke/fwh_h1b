# Choropleth Rendering (year dropdown + level toggle)

**Namespace(s):** `h1b.maps` (backing library) ·
**Library:** `src/h1b/_lib.py` (`_render_html`, `_attribution`, `build_h1b_map` render step, `RAMP`/`NODATA`/`OUTLIER`) ·
**Tests:** `tests/test_h1b.py` (`test_render_html_has_year_dropdown_and_toggle`)

## Overview

The presentation half of the pipeline: turn the state + county GeoJSON
FeatureCollections (each feature carrying a `y_<year>` count per fiscal year) into
one **self-contained MapLibre GL** HTML page with a **fiscal-year dropdown**, a
**state / county level toggle**, a name search box, and an "About this data" modal.
Every year is embedded in the page, so the dropdown re-colours client-side with no
server round-trip.

## How it works

`_render_html(state_fc, county_fc, years)` builds a single f-string HTML document:

1. **Embed data** — `STATE`, `COUNTY` FeatureCollections and `YEARS` are inlined as
   compact JSON; `RAMP` is the colour ramp.
2. **Colour scale** (`colorExpr` / `bounds` / `quantile`, client-side JS) — for the
   active level and selected year it takes the positive values, sorts them, and
   clamps the high end at the **90th percentile** (`quantile(a,0.90)`). A MapLibre
   `interpolate`/`linear` expression maps `[lo, hi]` across `RAMP`; values `≤0` or
   null → `NODATA` grey, values `> hi` → the `OUTLIER` purple (`#5e3c99`).
3. **Controls** — a `#year` `<select>` (`FY<year>` options), two `name="lvl"` radios
   (state/county). Changing the level swaps `map.getSource('d').setData(activeFc())`
   and thins the outline; changing either calls `refresh()` (repaint + legend).
4. **Interaction** — click a feature → a popup table of every fiscal year's count
   (selected year bolded); a search box fuzzy-matches `NAME` and `fitBounds` to the
   picked feature; an info button opens the modal.
5. **Attribution** — `_attribution()` stamps a fixed footer crediting the
   `h1b.workflows.BuildH1bVisaMap` workflow with links to the FFL source
   (`FFL_URL`) and repo, plus a UTC generation timestamp.

`build_h1b_map` writes the returned HTML to `output_root()/index.html` and the
county FeatureCollection to `counties.geojson`.

## Fan-out

**Single-task — no fan-out.** Rendering is a pure in-process string build; both
levels and all years render together in the one `BuildH1bMap` task.

## Data & fields

- **Per-feature:** `NAME`, `state` (county features), and one `y_<year>` integer per
  fiscal year in `years`. The colour/popup/legend JS reads `p['y_'+year]`.
- **Constants:** `RAMP` (5-stop sequential YlOrRd, light→dark = more approvals),
  `NODATA = "#e0e0e0"`, `OUTLIER = "#5e3c99"`. Simplify tolerances
  (`COUNTY_SIMPLIFY`/`STATE_SIMPLIFY`) are applied upstream in `build_h1b_map`, not
  here.
- No server-side filtering — filtering (search, level) is entirely client-side JS.

## External libraries / binaries

- **MapLibre GL JS + CSS 4.7.1** — loaded from `unpkg.com` CDN by the page; a
  client-side runtime dependency, **not** a Python/pip one.
- **CARTO Voyager raster basemap** — `basemaps.cartocdn.com` XYZ tiles (attribution
  "© OpenStreetMap © CARTO · USCIS").
- **Python:** stdlib only in the render path (`json`, `html.escape`,
  `datetime`) — the geometry work (`shapely` simplify/dissolve) happens in
  `build_h1b_map` before render.

## Facets & workflows

No dedicated facet — `_render_html` is the final step of `h1b.maps.BuildH1bMap` (see
[h1b-map](h1b-map.md)). `test_render_html_has_year_dropdown_and_toggle` asserts the
output contains `id="year"`, `name="lvl"`, "By county", `colorExpr`, `quantile`,
`#5e3c99`, `y_'+year`, and `'FY'+y` — the load-bearing UI probes.

## Cache / output

- **`index.html`** (the map) and **`counties.geojson`** (the simplified county
  FeatureCollection) under `storage.output_root()`. Fleet:
  `s3://afl-cache/cache/h1b/output/`; local: `<FW_DATA_ROOT>/h1b-output/`.
- The page is fully self-contained (data inlined) apart from the CDN MapLibre/basemap
  assets, so it can be opened directly or published to a static site.

## Gotchas & notes

- **p90 clamp is intentional.** A few employer hubs (large IT staffing firms) dwarf
  everyone; without the 90th-percentile cap + separate `OUTLIER` colour the ramp
  would be all-pale. Changing the cap changes the whole visual story.
- **State counts come from the state field, county counts from ZIP joins** — the two
  levels are computed independently upstream, so state ≠ sum of its counties (unjoined
  ZIPs). Expected, not a bug.
- **CDN dependency.** Offline viewers get no basemap/MapLibre; the choropleth data is
  still present in the page source.
- **Non-ASCII caution** (framework-wide): keep injected strings ASCII — FFL/runtime
  has a known non-ASCII literal mangling issue; this renderer's text is already ASCII.

## Related specs

- [h1b-map](h1b-map.md) — the facet that assembles geometry and calls this renderer.
- [data-ingest](data-ingest.md) / [zip-county-join](zip-county-join.md) — produce the
  `y_<year>` counts the map colours.
- [storage](storage.md) — where `index.html` / `counties.geojson` are written.
