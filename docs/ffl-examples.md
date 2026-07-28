# FFL Examples — `h1b`

Every numbered scenario is a **complete, compilable FFL file**. Copy one into
`my.ffl` and run it:

```bash
fw ffl run --primary my.ffl \
  --library ~/fw_handlers/fwh_h1b/src/h1b/ffl/h1b.ffl \
  --workflow my.h1b.<WorkflowName>
```

A runner serving the `h1b` namespace must be up (`fw runner start --domain h1b`).
Every block below is compile-checked against `src/h1b/ffl/h1b.ffl`.

New to the language? Start with the
[FFL grammar](https://github.com/rlemke/facetwork/blob/main/docs/reference/language/grammar.md)
and the [canonical examples](https://github.com/rlemke/facetwork/tree/main/examples/canonical).

---

## The facets at a glance

One event facet and the workflow that wraps it — a small surface that makes this a
good place to learn the language.

| Declaration | Signature | Does |
|---|---|---|
| `h1b.maps.BuildH1bMap` | `(force: Boolean = false) => (html_path, years, county_count, state_count)` | Fetch USCIS FY CSVs, aggregate by state + county, render the year-dropdown choropleth |
| `h1b.workflows.BuildH1bVisaMap` | `(force: Boolean = false) => (status, html_path, years, county_count)` | The shipped entry point |

`BuildH1bMap` is an `event facet`: it runs in a handler on a runner, not in the
compiler. Its `with Effect(kind = "external")` / `with Cost(tier = "expensive")`
mixins are what `fw_capabilities(effect=…, max_cost=…)` filters on.

---

## 1. Run what ships — no FFL to write

```bash
fw ffl seed --include h1b

fw ffl run --primary ~/fw_handlers/fwh_h1b/src/h1b/ffl/h1b.ffl \
  --workflow h1b.workflows.BuildH1bVisaMap \
  --inputs '{"force": false}'
```

`force = true` re-fetches the USCIS CSVs instead of using the cache. Note this
domain reuses the census-us cached county geometry — run a census map first.

Write FFL when you want a different shape of run — your own error handling, a
coverage guard, or composition with another domain.

## 2. The smallest workflow you can write

Every FFL workflow needs a `namespace`, a `use` per namespace it calls into, and a
`yield` back to itself.

```ffl
namespace my.h1b {

    use h1b.maps

    /** Build the H-1B approvals map. */
    workflow MyH1bMap() => (html_path: String, counties: Int) andThen {

        map = h1b.maps.BuildH1bMap(force = false)

        yield MyH1bMap(html_path = map.html_path, counties = map.county_count)
    }
}
```

Three rules visible above: `=>` sits on the **same line** as the closing `)` of the
parameter list; references are always `step.field` (never a bare step name); and a
workflow ends by yielding to itself.

## 3. Parameters and `$`

`$` means "my immediate container" — inside a workflow body that's the workflow, so
`$.force` is its parameter. `$$` walks one level out (into an enclosing block).

```ffl
namespace my.h1b {

    use h1b.maps

    /** Rebuild, optionally re-fetching the USCIS data. */
    workflow RefreshH1bMap(force: Boolean = false) => (status: String, html_path: String, coverage: Int) andThen {

        map = h1b.maps.BuildH1bMap(force = $.force)

        yield RefreshH1bMap(
            status = "completed",
            html_path = map.html_path,
            coverage = map.years)
    }
}
```

Run with `--inputs '{"force": true}'`.

## 4. Call-time mixins — timeouts and retries

The facet declares its own defaults (`with Timeout(minutes = 30)`); the **call
site** can add or override mixins for one particular use without forking the facet.
Fifteen fiscal years of CSV plus a ZIP→county spatial join is the expensive part.

```ffl
namespace my.h1b {

    use h1b.maps

    /** Give the full-history rebuild room, and retry USCIS hiccups. */
    workflow ResilientH1bMap() => (html_path: String) andThen {

        map = h1b.maps.BuildH1bMap(force = true) with Timeout(minutes = 90) with Retry(maxAttempts = 3, backoffSeconds = 120)

        yield ResilientH1bMap(html_path = map.html_path)
    }
}
```

## 5. Survive a failed fetch — `catch`

`catch` runs when its step errors after retries are exhausted. Yielding from the
catch block ends the run with a partial result instead of a hard failure.

```ffl
namespace my.h1b {

    use h1b.maps

    /** Report a partial result rather than failing the run. */
    workflow BestEffortH1bMap() => (status: String, html_path: String) andThen {

        map = h1b.maps.BuildH1bMap(force = true) catch {
            yield BestEffortH1bMap(status = "uscis_fetch_failed", html_path = "")
        }

        yield BestEffortH1bMap(status = "completed", html_path = map.html_path)
    }
}
```

## 6. Branch on a result — `when`

A `when` block hangs off the step it inspects: inside a case `$` is that step and
`$$` reaches the workflow's parameters. Every `when` needs a default case, last,
and conditions must be real `Boolean`s (no truthy coercion).

```ffl
namespace my.h1b {

    use h1b.maps

    /** Guard the ZIP→county join: a thin county count means the geometry cache is cold. */
    workflow VerifiedH1bMap(min_counties: Int = 2000) => (status: String, html_path: String) andThen {

        map = h1b.maps.BuildH1bMap() andThen when {
            case $.county_count >= $$.min_counties => {
                yield VerifiedH1bMap(status = "complete_join", html_path = $.html_path)
            }
            case _ => {
                yield VerifiedH1bMap(status = "thin_join_run_census_first", html_path = $.html_path)
            }
        }
    }
}
```

## 7. Reuse the shipped workflow

Workflows compose like facets — wrap `BuildH1bVisaMap` rather than forking it.

```ffl
namespace my.h1b {

    use h1b.workflows

    /** Wrap the shipped workflow and reshape its result. */
    workflow H1bWithHeadline() => (headline: String) andThen {

        built = h1b.workflows.BuildH1bVisaMap(force = false)

        yield H1bWithHeadline(headline = "h1b map: " ++ built.status)
    }
}
```

## 8. Compose across domains — publish the map

Facets from different domains compose in one workflow as long as some runner in
the fleet serves each namespace. `census.Publish` is the generic publisher the map
domains share.

```ffl
namespace my.h1b {

    use h1b.maps
    use census.Publish

    /** Render, then push to the public maps site. */
    workflow H1bPublish(repo: String = "rlemke/facetwork-maps") => (pages_url: String) andThen {

        map = h1b.maps.BuildH1bMap()

        published = census.Publish.PublishWebBundle(
            repo = $.repo,
            prefixes = ["h1b/output"],
            dests = ["us/h1b"],
            labels = ["H-1B approvals by state & county"],
            landing_title = "Facetwork maps")

        yield H1bPublish(pages_url = published.pages_url)
    }
}
```

Compile that one with `--library ~/fw_handlers/fwh_census_us/src/census_us/ffl/census.ffl`
as well.

---

## Cheat sheet

| You want to… | Write |
|---|---|
| Read a workflow/step parameter | `$.name` (`$$.name` one level out) |
| Read a previous step's result | `stepname.field` |
| Order two independent steps | reference a field of the first from the second |
| More time / retries for one call | `… with Timeout(minutes = 90) with Retry(maxAttempts = 3, backoffSeconds = 120)` |
| Handle a step failure | `step = Facet(…) catch { yield … }` |
| Branch | `step = Facet(…) andThen when { case <bool> => { … } case _ => { … } }` |
| Fan out over a list | `workflow W(items: Json) … andThen foreach i in $.items { … }` |
| Concatenate strings | `a ++ b` |

**Validate before you run:** `afl my.ffl --check` or MCP `fw_validate`. Every error
carries a `rule_id` — fetch `fw://docs/rules/{rule_id}` for a wrong/right pair.

## See also

- [`docs/README.md`](README.md) — per-feature specs for this domain
- [`docs/h1b-map.md`](h1b-map.md) — what the single facet actually does
- [FFL grammar](https://github.com/rlemke/facetwork/blob/main/docs/reference/language/grammar.md) ·
  [canonical examples](https://github.com/rlemke/facetwork/tree/main/examples/canonical) ·
  [relative `$`-scoping](https://github.com/rlemke/facetwork/blob/main/docs/architecture/ffl-relative-scoping.md)
- `src/h1b/ffl/h1b.ffl` — the source of truth for every signature above
