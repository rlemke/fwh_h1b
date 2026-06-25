"""h1b domain — H-1B visa approvals by US state & county, multi-year.

Discovered by the Facetwork runner via the ``facetwork.domains`` entry point::

    [project.entry-points."facetwork.domains"]
    h1b = "h1b:domain"
"""

from __future__ import annotations

from pathlib import Path

from facetwork.domains import DomainPackage

from .handlers import register_all_registry_handlers

domain = DomainPackage(
    name="h1b",
    ffl_dir=Path(__file__).parent / "ffl",
    register_handlers=register_all_registry_handlers,
    runner_env={
        "AFL_TASK_EXECUTION_TIMEOUT_MS": "1800000",  # 30 min (15 CSV fetch + ZIP join; cached after)
        "AFL_STUCK_TIMEOUT_MS": "2100000",
    },
)
