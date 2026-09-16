"""Executive summary wording and setup-aware UI helpers."""

import pandas as pd
from test_formulas import INSIGHTS, ISSUES, PRS, SERVICE_SESSIONS, SESSIONS, F

from devin_kpi.app.ui import delta_color, md_escape, needs_setup, split_configured
from devin_kpi.config import Settings
from devin_kpi.kpis.filters import previous_period
from devin_kpi.kpis.formulas import KpiValue, compute_all
from devin_kpi.kpis.summary import executive_summary


def _kvs(settings, sessions=SESSIONS, f=F):
    out = compute_all(sessions, PRS, INSIGHTS, ISSUES, pd.DataFrame(), f, settings)
    return {k.key: k for k in out}


def test_summary_covers_delivery_cost_adoption_and_risk():
    settings = Settings(DEVIN_API_KEY="k", ACU_UNIT_PRICE=2.0, SEAT_COUNT=10)
    all_s = pd.concat([SESSIONS, SERVICE_SESSIONS], ignore_index=True)
    lines = executive_summary(_kvs(settings, all_s), _kvs(settings, all_s, previous_period(F)))
    text = "\n".join(lines)
    assert "**2 pull requests**" in text
    assert "67% of the PRs it opened were merged" in text
    assert "Total spend was **$44.00**" in text
    assert "$22.00 per merged PR" in text  # 22 ACUs * $2 / 2 merged PRs
    assert "**5 engineers** used Devin in the last 30 days" in text
    assert "vs prior period" in text  # previous period has s5, so a trend renders
    assert "17% of sessions were stopped by usage limits" in text
    assert "17% ended in error" in text
    assert 2 <= len(lines) <= 4


def test_summary_falls_back_to_acus_without_price():
    lines = executive_summary(_kvs(Settings(DEVIN_API_KEY="k")))
    text = "\n".join(lines)
    assert "Total spend" not in text
    assert "consumed **20 ACUs**" in text
    assert "10.0 ACUs per merged PR" in text
    # zero-rate watch items are omitted, and no takeover data -> no risk line
    assert "Watch items" not in text


def test_summary_omits_sentences_without_inputs():
    assert executive_summary({}) == []
    only = {"mau": KpiValue("mau", "Adoption", "MAU", 7.0, "users")}
    assert executive_summary(only) == ["**7 engineers** used Devin in the last 30 days."]


def test_split_configured_hides_only_setup_gaps():
    ok = KpiValue("a", "g", "A", 1.0, "count")
    no_data = KpiValue("b", "g", "B", None, "count", available=False)
    needs_price = KpiValue(
        "c", "g", "C", None, "usd", available=False, depends_on=["ACU_UNIT_PRICE"]
    )
    configured_dep = KpiValue("d", "g", "D", 2.0, "usd", depends_on=["ACU_UNIT_PRICE"])
    assert not needs_setup(ok)
    assert not needs_setup(no_data)  # empty period is not a setup problem
    assert needs_setup(needs_price)
    assert not needs_setup(configured_dep)
    shown, hidden = split_configured([ok, no_data, needs_price, configured_dep])
    assert [k.key for k in shown] == ["a", "b", "d"]
    assert [k.key for k in hidden] == ["c"]


def test_delta_color_is_neutral_when_delta_rounds_to_zero():
    takeover = KpiValue("human_takeover_rate", "g", "T", 0.0421, "ratio")
    assert delta_color(takeover, 0.0421) == "off"
    assert delta_color(takeover, 0.0425) == "off"  # renders as +0.0 pp
    assert delta_color(takeover, 0.0300) == "inverse"
    msgs = KpiValue("avg_user_messages", "g", "M", 2.5, "count")
    assert delta_color(msgs, 2.6) == "off"  # renders as -0
    assert delta_color(msgs, 1.0) != "off"


def test_md_escape_protects_dollar_amounts_from_latex():
    assert md_escape("Total spend was **$20,957** ($30.82 per PR)") == (
        "Total spend was **\\$20,957** (\\$30.82 per PR)"
    )
