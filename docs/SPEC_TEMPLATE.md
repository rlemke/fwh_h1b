<!-- SPEC TEMPLATE — every docs/<feature>.md follows this shape so the set reads
consistently. Delete this comment in real specs. Keep sections in this order;
omit a section only if it genuinely does not apply (say so in one line rather
than dropping the heading silently). Ground every claim in the actual FFL
docstrings / handler code / storage helpers — do not invent behaviour. -->

# <Feature Name>

**Namespace(s):** `h1b.<ns>` · **FFL:** `src/h1b/ffl/h1b.ffl` ·
**Handlers:** `src/h1b/handlers/h1b_handlers.py` · **Library:** `src/h1b/_lib.py` ·
**Storage:** `src/h1b/storage.py` (if relevant)

## Overview
One or two paragraphs: what this feature is for, the request it answers, and where
it sits in the pipeline (fetch → aggregate → join → render).

## How it works
The algorithm / data flow, step by step. Name the concrete functions and the shape
of the data at each (USCIS CSV → per-year aggregate JSON → GeoJSON FeatureCollection
→ HTML map). If there is a source/analysis split, say so.

## Fan-out
Does it fan out across the fleet? If yes: what is the fan-out unit and which facet
drives it. If it is single-task, say "single-task — no fan-out" and why (e.g. one
atomic multi-year build, small aggregate output).

## Data & fields
What data it reads and which fields it keys on — be specific (USCIS columns
`Initial Approval`/`Initial Approvals`, `Continuing Approval`, `State`, `ZIP`;
census `GEOID`/`NAME`/`STATEFP`/`population`; ZIP `code`/`lat`/`lon`). Name the
join/aggregation mechanism (a `defaultdict` accumulator by state name / county
GEOID, a shapely point-in-polygon spatial join, a `unary_union` dissolve). If the
feature does no filtering/keying, say so.

## External libraries / binaries
Every non-stdlib dependency this feature relies on and what for — e.g. `requests`
(HTTP fetch), `shapely` (geometry + STRtree spatial index + dissolve), `boto3`
(S3 listing on the fleet), MapLibre GL JS (CDN, client-side only). Distinguish a
**pip** dependency from a client-side **CDN** one.

## Facets & workflows
The key event facets and workflows, with signatures and a one-line purpose taken
from the FFL `/** … */` docstrings. Mark event facets (need a handler) vs pure
facets/workflows, and note `Effect`/`Cost`/`Timeout` mixins where present.

## Cache / output
The cache namespace under `$FW_DATA_ROOT/cache/h1b/` (or the local `h1b-cache` /
`h1b-output` dirs) and the cache artifacts (`h1b-aggregate.json`,
`zip-to-geoid.json`), plus the output artifact(s) and format (`index.html` map,
`counties.geojson`). Note whether outputs go to local disk or MinIO/S3.

## Gotchas & notes
Known pitfalls, rate limits, sensitivity caveats, or non-obvious constraints
(worth capturing anything a future maintainer would trip on).

## Related specs
Links to the specs this feature composes with or depends on.
