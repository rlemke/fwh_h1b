# h1b — Feature Specifications

This directory holds one **spec per feature** of the h1b domain (US H-1B visa
approvals by state & county, FY2009–FY2023). Each document follows a common shape
([`SPEC_TEMPLATE.md`](SPEC_TEMPLATE.md)) and states, for that feature: how it works,
whether and how it **fans out** across the fleet, the **data & fields** it keys on,
the **external libraries** it relies on, its **facets & workflows**, and its
**cache/output**. Claims are grounded in the FFL `/** … */` docstrings
(`src/h1b/ffl/h1b.ffl`), the library (`src/h1b/_lib.py`), the handler
(`src/h1b/handlers/h1b_handlers.py`), and the storage helper (`src/h1b/storage.py`).

This is a compact single-map domain — one event facet (`h1b.maps.BuildH1bMap`) and
one workflow (`h1b.workflows.BuildH1bVisaMap`) — so the feature set is the map plus
its four internal stages.

**Start here:** [**H-1B Visa-Approvals Map**](h1b-map.md) — the flagship spec (the
full fetch → aggregate → join → render pipeline and the facet/workflow surface).

## Flagship

| Spec | What it covers |
|------|----------------|
| [h1b-map.md](h1b-map.md) | **Flagship.** The `BuildH1bMap` event facet + `BuildH1bVisaMap` workflow: the end-to-end multi-year, state+county choropleth pipeline, its single-task (no fan-out) shape, and the census-geometry-reuse dependency. |

## Data ingest & join

| Spec | What it covers |
|------|----------------|
| [data-ingest.md](data-ingest.md) | USCIS H-1B Employer Data Hub CSV fetch + state/county aggregation; the `Initial/Continuing Approval(s)` column-rename handling; approvals-not-LCA distinction. |
| [zip-county-join.md](zip-county-join.md) | ZIP-centroid → county GEOID spatial join (shapely STRtree point-in-polygon) and the reuse of the shared census-us county geometry. |

## Rendering & storage

| Spec | What it covers |
|------|----------------|
| [visualization.md](visualization.md) | The self-contained MapLibre choropleth: fiscal-year dropdown, state/county toggle, p90-clamp colour scale + outlier purple, search, "About this data" modal, attribution. |
| [storage.md](storage.md) | Backend-aware cache/output (`storage.py`): local `h1b-cache`/`h1b-output` vs `s3://afl-cache/cache/h1b/…`, the stage-local-then-finalize write, and the cross-domain census cache read. |
| [ffl-examples.md](ffl-examples.md) | **Usage patterns.** A gallery of complete, compile-checked FFL examples over this domain's facet — minimal workflow, `$`-scoping, call-time mixins, `catch`, `when` join guards, cross-domain publish. |

---

*See also the repo [`README.md`](../README.md) (domain overview + data sources) and
the FFL source of truth at [`src/h1b/ffl/h1b.ffl`](../src/h1b/ffl/h1b.ffl). The
live/queryable interface is the MCP `fw_capabilities` / `fw_describe_handler` tools.*
