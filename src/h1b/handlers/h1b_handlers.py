"""Event facet handler for the h1b domain — thin layer over ``_lib``."""

from __future__ import annotations

import os
from typing import Any

from .._lib import build_h1b_map

MAPS = "h1b.maps"


def handle_build_h1b_map(params: dict[str, Any]) -> dict[str, Any]:
    """Aggregate USCIS H-1B approvals by state+county across years + render."""
    step_log = params.get("_step_log")
    try:
        res = build_h1b_map(force=bool(params.get("force")))
        if step_log:
            step_log(
                f"BuildH1bMap: {res.years} years -> "
                f"{res.county_count} counties / {res.state_count} states "
                f"-> {res.html_path}",
                level="success",
            )
        return {
            "html_path": res.html_path,
            "years": res.years,
            "county_count": res.county_count,
            "state_count": res.state_count,
        }
    except Exception as exc:
        if step_log:
            step_log(f"BuildH1bMap: {exc}", level="error")
        raise


_DISPATCH: dict[str, Any] = {
    f"{MAPS}.BuildH1bMap": handle_build_h1b_map,
}


def handle(payload: dict) -> dict:
    return _DISPATCH[payload["_facet_name"]](payload)


def register_handlers(runner) -> None:
    for facet_name in _DISPATCH:
        runner.register_handler(
            facet_name=facet_name,
            module_uri=f"file://{os.path.abspath(__file__)}",
            entrypoint="handle",
            timeout_ms=0,  # long blocking multi-CSV fetch (cached after first run)
        )


def register_poller(poller) -> None:
    for facet_name, handler in _DISPATCH.items():
        poller.register(facet_name, handler)
