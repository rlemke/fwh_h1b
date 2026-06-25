# h1b

A standalone [Facetwork](https://github.com/rlemke/facetwork) domain that maps
**H-1B visa approvals by US state & county**, with a **fiscal-year dropdown**
(FY2009–FY2023).

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
