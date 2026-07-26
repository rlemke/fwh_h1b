# h1b

A standalone [Facetwork](https://github.com/rlemke/facetwork) domain that maps
**H-1B visa approvals by US state & county**, with a **fiscal-year dropdown**
(FY2009–FY2023).

## Feature specifications

Per-feature docs live in [`docs/`](docs/README.md) — one spec per feature, each
covering how it works, fan-out, data/fields, external libraries, facets, and
cache/output.

| Spec | What it covers |
|------|----------------|
| [docs/h1b-map.md](docs/h1b-map.md) | **Flagship** — the `BuildH1bMap` facet + `BuildH1bVisaMap` workflow: the full fetch → aggregate → join → render pipeline. |
| [docs/data-ingest.md](docs/data-ingest.md) | USCIS CSV fetch + state/county aggregation (approval-column rename handling). |
| [docs/zip-county-join.md](docs/zip-county-join.md) | ZIP-centroid → county GEOID spatial join; census-geometry reuse. |
| [docs/visualization.md](docs/visualization.md) | The MapLibre year-dropdown / state-county-toggle choropleth renderer. |
| [docs/storage.md](docs/storage.md) | Backend-aware cache/output (local vs MinIO/S3). |

Full index: [`docs/README.md`](docs/README.md).

- **Source** — the **USCIS H-1B Employer Data Hub** per-fiscal-year CSVs (actual
  approved petitions: Initial + Continuing, by employer, with State / City / ZIP).
  *Not* the DOL LCA disclosure data (those are certified positions / applications,
  far more numerous than real visas).
- **`h1b.maps.BuildH1bMap`** — fetches each FY CSV, aggregates approvals by **state**
  (State field) and **county** (employer ZIP → county GEOID via a ZIP-centroid
  point-in-polygon against census county polygons), attaches every year to every
  feature, dissolves counties → state polygons, and renders a MapLibre choropleth
  with a **year dropdown** + **state/county toggle** (darker = more approvals;
  p90-clamped scale, high outliers in purple; search; click-for-history).
- **Workflow** — `h1b.workflows.BuildH1bVisaMap`.
- Reuses the census-us cached county geometry (shared MinIO) — run a census map first.

**Caveat:** USCIS reports the *petitioning employer's address*, not the worker's
worksite, so state/county reflect where the employer is registered.

Data: USCIS H-1B Employer Data Hub (public domain); county geometry from US Census
TIGER; ZIP centroids from the midwire free US ZIP dataset.
