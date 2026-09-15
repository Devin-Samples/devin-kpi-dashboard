"""Synthetic generator invariants."""

import pandas as pd

from devin_kpi.store import Store
from devin_kpi.synth.generate import generate


def test_generate(tmp_path):
    store = Store(tmp_path / "demo.sqlite")
    stats = generate(store, seed=42, n_sessions=800, n_days=60)

    assert store.count("sessions") == stats["sessions"] == 800
    assert store.count("session_insights") == 800
    assert store.count("session_prs") == stats["prs"]
    assert stats["prs"] / 800 == pytest_approx(0.55, tol=0.08)

    prs = store.read_df("session_prs")
    merged_frac = (prs.pr_state == "merged").mean()
    assert 0.5 < merged_frac < 0.75

    # consumption total ~= session ACUs (same sessions, product split)
    cons = store.read_df("consumption_daily", "product = 'total' AND scope = 'organization'")
    sess = store.read_df("sessions")
    assert cons.acus.sum() == pytest_approx(sess.acus_consumed.sum(), tol=0.02)

    # determinism
    store2 = Store(tmp_path / "demo2.sqlite")
    generate(store2, seed=42, n_sessions=800, n_days=60)
    pd.testing.assert_frame_equal(
        store.read_df("sessions").sort_values("session_id").reset_index(drop=True),
        store2.read_df("sessions").sort_values("session_id").reset_index(drop=True),
    )

    assert store.get_meta("demo") == "true"
    assert store.count("billing_cycles") > 0
    assert store.count("audit_logs") == 60


def pytest_approx(x, tol=1e-6):
    import pytest

    return pytest.approx(x, rel=tol, abs=tol)
