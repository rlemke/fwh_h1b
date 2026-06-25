"""Offline tests for the h1b domain (no network)."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

SRC = str(Path(__file__).resolve().parent.parent / "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

from h1b import _lib  # noqa: E402
from h1b.handlers import h1b_handlers as hh  # noqa: E402


def test_num_parsing():
    assert _lib._num("1,234") == 1234
    assert _lib._num("") == 0
    assert _lib._num(None) == 0
    assert _lib._num("abc") == 0


def test_state_abbr_map():
    assert _lib.STATE_ABBR["CA"] == "California"
    assert _lib.STATE_ABBR["DC"] == "District of Columbia"
    assert len(_lib.STATE_ABBR) == 51  # 50 states + DC


def test_years_range():
    assert _lib.YEARS[0] == 2009 and _lib.YEARS[-1] == 2023


def test_dispatch_and_register():
    assert set(hh._DISPATCH) == {"h1b.maps.BuildH1bMap"}
    runner = MagicMock()
    hh.register_handlers(runner)
    assert runner.register_handler.call_count == 1
    assert runner.register_handler.call_args.kwargs.get("timeout_ms") == 0


def test_render_html_has_year_dropdown_and_toggle():
    state_fc = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
         "properties": {"NAME": "California", "y_2023": 32585, "y_2022": 30000}}]}
    html = _lib._render_html(state_fc, state_fc, [2022, 2023])
    for probe in ['id="year"', 'name="lvl"', "By county", "colorExpr", "quantile",
                  "#5e3c99", "y_'+year", "'FY'+y"]:
        assert probe in html, probe
