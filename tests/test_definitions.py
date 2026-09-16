"""Registry coverage: every KpiValue key exists in DEFINITIONS and vice versa."""

import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from test_formulas import INSIGHTS, ISSUES, PRS, SESSIONS

from devin_kpi.config import Settings
from devin_kpi.kpis.definitions import DEFINITIONS
from devin_kpi.kpis.filters import FilterSet
from devin_kpi.kpis.formulas import compute_all


def test_registry_matches_computed_keys():
    settings = Settings(DEVIN_API_KEY="k")
    f = FilterSet(start=datetime(2024, 1, 1, tzinfo=UTC), end=datetime(2024, 4, 1, tzinfo=UTC))
    keys = {
        k.key for k in compute_all(SESSIONS, PRS, INSIGHTS, ISSUES, pd.DataFrame(), f, settings)
    }
    assert keys == set(DEFINITIONS)


def test_gen_definitions_md():
    from gen_definitions_md import render

    md = render()
    for key in DEFINITIONS:
        assert f"`{key}`" in md
