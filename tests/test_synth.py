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

    # service accounts: every code_scan/automation session has one, and
    # human sessions never do
    svc = sess[sess.origin.isin(["code_scan", "automation"])]
    assert svc.service_user_id.notna().all()
    assert sess[sess.origin.isin(["webapp", "slack", "desktop"])].service_user_id.isna().all()
    assert 0 < svc.service_user_id.nunique() <= 4

    # audit log: login + create_session per human session, plus extras;
    # actor column never holds an email
    audit = store.read_df("audit_logs")
    n_human = int(sess.service_user_id.isna().sum())
    assert (audit.event_type == "login").sum() == n_human
    assert (audit.event_type == "create_session").sum() == n_human
    assert audit.event_type.nunique() >= 8
    assert not audit.actor.str.contains("@").any()


def pytest_approx(x, tol=1e-6):
    import pytest

    return pytest.approx(x, rel=tol, abs=tol)
