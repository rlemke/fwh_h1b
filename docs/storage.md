# Backend-aware Cache & Output

**Namespace(s):** cross-cutting (no facet) ·
**Storage:** `src/h1b/storage.py`
(`cache_root`, `output_root`, `_data_root`, `join`, `is_remote`, `exists`, `localize`, `open_read`, `open_write`) ·
**Consumers:** `src/h1b/_lib.py`

## Overview

Every cache and output path in the domain flows through `storage.py`, a thin wrapper
over `facetwork.runtime.storage` that makes the same code work against a **local
filesystem** (terminal use) or **MinIO/S3** (the fleet). It is the reason a fleet
runner and a laptop share one logical cache rooted at `$FW_DATA_ROOT/cache/h1b/`.
This is the same shape census-us / conflict / save-earth use (per the module
docstring).

## How it works

- **Root** — `_data_root()` = `FW_DATA_ROOT` or `facetwork.config.get_output_base()`.
  `is_remote(path)` = the path contains `://`.
- **Path layout** — `cache_root()` and `output_root()` branch on remoteness:
  - Remote: `join(root, "cache", "h1b", "cache")` and `.../h1b/output`
    (e.g. `s3://afl-cache/cache/h1b/{cache,output}`).
  - Local: `join(root, "h1b-cache")` and `join(root, "h1b-output")`.
  - Overridable via `FW_H1B_CACHE_DIR` / `FW_H1B_OUTPUT_DIR`.
- **`join(*parts)`** — a URL/path-safe join that preserves the scheme on the first
  part and strips stray slashes on the rest.
- **I/O**:
  - `exists(path)` → `get_storage_backend(path).exists`.
  - `open_read` localizes a remote object first (`_fws.localize`) then opens locally.
  - `open_write` writes local files directly (creating parent dirs); for remote
    paths it writes to a `tempfile`, then streams the temp file into the backend
    `open(path, "wb")` on close — a **stage-local-then-finalize** pattern (object
    stores have no partial writes).

## Fan-out

Not applicable — this is shared infrastructure, not a task. It is what *makes*
single-host outputs resolvable across a multi-host fleet (portable `s3://` URIs).

## Data & fields

Handles opaque blobs — the JSON aggregates (`h1b-aggregate.json`,
`zip-to-geoid.json`), the GeoJSON (`counties.geojson`), and the HTML map
(`index.html`). No schema of its own beyond the path conventions above.

## External libraries / binaries

- **`facetwork.runtime.storage`** — the actual backend (`get_storage_backend`,
  `localize`) selected by `FW_STORAGE` (`local` / `s3` / `hdfs`).
- **`facetwork.config.get_output_base`** — the default data root.
- **stdlib** `os` / `tempfile` / `contextlib`. `boto3` is used by `_lib`
  (`_list_census_states`), not by `storage.py` itself.

## Facets & workflows

None — `storage.py` exposes no facet. It is imported as `cstore` throughout `_lib`.

## Cache / output

This *is* the cache/output layer. Summary of what lands where (fleet paths shown):

| Artifact | Path (remote) | Producer |
|---|---|---|
| `h1b-aggregate.json` | `s3://afl-cache/cache/h1b/cache/` | [data-ingest](data-ingest.md) |
| `zip-to-geoid.json` | `s3://afl-cache/cache/h1b/cache/` | [zip-county-join](zip-county-join.md) |
| `counties.geojson` | `s3://afl-cache/cache/h1b/output/` | [visualization](visualization.md) |
| `index.html` | `s3://afl-cache/cache/h1b/output/` | [visualization](visualization.md) |

Locally these become `<FW_DATA_ROOT>/h1b-cache/…` and `<FW_DATA_ROOT>/h1b-output/…`.

## Gotchas & notes

- **Keep scratch local.** `open_write` stages to a local `tempfile` before
  finalizing to S3; the temp dir must stay on local disk (the framework-wide
  `FW_LOCAL_SCRATCH`/`FW_OUTPUT_BASE` guidance).
- **Reads two caches.** The h1b cache is under `cache/h1b/`, but `_lib` also *reads*
  the **census-us** cache (`cache/census-us/output/metrics`) via the same `_data_root`
  — a cross-domain read on the shared store (see [zip-county-join](zip-county-join.md)).
- **Env overrides win.** `FW_H1B_CACHE_DIR` / `FW_H1B_OUTPUT_DIR` bypass the
  local/remote branching entirely — handy for pointing a test at a temp dir.

## Related specs

- [data-ingest](data-ingest.md), [zip-county-join](zip-county-join.md) — cache
  producers/consumers.
- [visualization](visualization.md) — writes the output artifacts.
- [h1b-map](h1b-map.md) — the facet that ties all of these together.
