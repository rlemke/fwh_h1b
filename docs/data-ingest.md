# USCIS Data Ingest & Aggregation

**Namespace(s):** `h1b.maps` (backing library) ·
**Library:** `src/h1b/_lib.py` (`download_h1b`, `_approvals`, `_col`, `_num`, `STATE_ABBR`) ·
**Storage:** `src/h1b/storage.py`

## Overview

The ingest half of the pipeline: fetch the **USCIS H-1B Employer Data Hub**
per-fiscal-year CSVs and aggregate approved petitions into a compact per-year
count by **state** and by **county**. This is the authoritative "how many H-1B
visas were approved" layer that the map colours.

The source is deliberately the USCIS *Employer Data Hub* — **actual approved
petitions** (Initial + Continuing), by employer, with State / City / ZIP — and
**not** the DOL LCA disclosure feed (certified positions / applications, far more
numerous than real visas). The `_lib` module docstring and README both call this
out explicitly.

## How it works

`download_h1b(force=False)` (`_lib.py`):

1. **Cache gate** — returns the cached `h1b-aggregate.json` unless `force=True`
   (`cstore.exists` / `open_read`).
2. **ZIP map** — builds/loads `zip2geoid` via `_zip_to_geoid()` (see
   [zip-county-join](zip-county-join.md)) so county assignment is available during
   the row scan.
3. **Per-year fetch** — for each `y in YEARS` (2009–2023) it GETs
   `USCIS_CSV.format(y=y)`
   (`https://www.uscis.gov/sites/default/files/document/data/h1b_datahubexport-{y}.csv`)
   with a browser `User-Agent`, 120 s timeout. Non-200 or a fetch exception is
   **logged and skipped**, not fatal — the map simply omits that year.
4. **Row aggregation** — each employer row contributes `_approvals(row)` to:
   - `by_state[STATE_ABBR[row["State"]]][fy]` — 2-letter → full state name; rows
     whose state isn't in `STATE_ABBR` are dropped from the state layer.
   - `by_county[zip2geoid[row["ZIP"][:5]]][fy]` — only when the ZIP resolves to a
     county GEOID.
   Rows with `appr <= 0` are skipped.
5. **Persist** — writes `{"years": [...], "state": by_state, "county": by_county}`
   as JSON to `cache_root()/h1b-aggregate.json`.

Data shape: `15 × USCIS CSV → nested defaultdict counters → one aggregate JSON`.

## Fan-out

**Single-task — no fan-out.** All years are fetched sequentially inside the one
`BuildH1bMap` task. There is no per-year fleet distribution; the 15-fetch cost is
why the domain sets a 30-min task timeout and `timeout_ms=0` on the handler.

## Data & fields

- **Approvals** (`_approvals` → `_col` → `_num`): sum of
  `Initial Approval` **or** `Initial Approvals`, plus `Continuing Approval` **or**
  `Continuing Approvals`. The `_col` first-present lookup exists because USCIS
  **renamed** these columns — FY2009–2019 use the plural, FY2021+ the singular.
- **`_num`** strips commas/whitespace and coerces to `int`, returning `0` for
  blank / non-numeric / `None`.
- **State** (`row["State"]`): 2-letter code, upper-cased, mapped through
  `STATE_ABBR` (50 states + DC = 51 entries; asserted in `test_state_abbr_map`).
- **ZIP** (`row["ZIP"]`): first 5 chars, resolved to county GEOID.
- **`csv.field_size_limit(20_000_000)`** is raised at import so the large employer
  CSVs parse.

## External libraries / binaries

- **`requests`** (pip) — the CSV HTTP fetches. `requests is None` (import failure)
  raises `RuntimeError("requests is required to download the USCIS data")` on a
  cache miss.
- **stdlib** `csv` / `io` / `json` / `collections.defaultdict` — parsing and
  accumulation. No binary dependencies in this feature.

## Facets & workflows

No dedicated facet — `download_h1b` is an internal step of the
`h1b.maps.BuildH1bMap` event facet (see [h1b-map](h1b-map.md) for the facet
signature and mixins). It is exercised offline by `tests/test_h1b.py`
(`test_num_parsing`, `test_state_abbr_map`, `test_years_range`).

## Cache / output

- **`h1b-aggregate.json`** under `storage.cache_root()` — the sole artifact of this
  feature. Fleet: `s3://afl-cache/cache/h1b/cache/`; local:
  `<FW_DATA_ROOT>/h1b-cache/`. Small (per-year integer counters only, not the raw
  CSVs).
- No map/HTML output here — that's [visualization](visualization.md).

## Gotchas & notes

- **Column drift is real and handled.** Do not hard-code `Initial Approvals`; the
  `_col` fallback is load-bearing for FY2021+ (singular) vs FY2009–2019 (plural).
- **Missing years fail soft.** A year whose CSV 404s or times out is skipped with a
  warning; `years` in the aggregate reflects only successfully fetched years, and the
  map's dropdown shows exactly those.
- **`force` re-fetches CSVs only.** It does not rebuild `zip-to-geoid.json`.
- **County counts undercount slightly** relative to state counts: rows whose ZIP
  doesn't resolve to a county centroid-in-polygon are counted at state level but not
  county level.

## Related specs

- [zip-county-join](zip-county-join.md) — how `row["ZIP"]` becomes a county GEOID.
- [h1b-map](h1b-map.md) — the facet/workflow that drives this ingest.
- [storage](storage.md) — where `h1b-aggregate.json` lands.
