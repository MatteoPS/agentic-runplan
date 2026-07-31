from datetime import datetime, timedelta

from mc.rules import (
    Override,
    append_override,
    check_override_drift,
    check_rolling_compliance,
    count_overrides_in_window,
    parse_override,
    validate_reason_code,
)


# --- E1: closed reason-code set --------------------------------------------------


def test_e1_valid_code_passes():
    assert validate_reason_code("TRAVEL").allowed


def test_e1_invalid_code_rejected():
    result = validate_reason_code("I_FEEL_TIRED")
    assert not result.allowed
    assert result.violations[0].rule_id == "E1"


def test_e1_i_feel_tired_is_not_a_reason_code():
    # explicit per spec: "'I feel tired' is not a reason code"
    result = validate_reason_code("I feel tired")
    assert not result.allowed


def test_e1_readiness_requires_cited_data():
    result = validate_reason_code("READINESS", readiness_data_cited=None)
    assert not result.allowed


def test_e1_readiness_with_cited_data_passes():
    result = validate_reason_code("READINESS", readiness_data_cited="HRV 32ms, 8pts below 7d baseline")
    assert result.allowed


# --- E4: OVERRIDE must be a literal typed string, never assumed ------------------


def test_e4_parses_literal_override():
    o = parse_override("OVERRIDE: felt strong, extending easy run")
    assert o is not None
    assert o.detail == "felt strong, extending easy run"


def test_e4_does_not_assume_override_from_other_phrasing():
    assert parse_override("I want to override this") is None
    assert parse_override("let's just skip the rule today") is None
    # case-sensitive on purpose: "never assume" means only the literal typed
    # form counts, not a lowercase near-miss that merely resembles it.
    assert parse_override("override: lowercase should not count") is None


def test_e4_empty_reason_rejected():
    assert parse_override("OVERRIDE:") is None
    assert parse_override("OVERRIDE:   ") is None


def test_e4_override_extracts_known_reason_code_when_present():
    o = parse_override("OVERRIDE: TRAVEL - flight delayed a day")
    assert o.reason_code == "TRAVEL"


def test_e4_override_falls_back_to_generic_code():
    o = parse_override("OVERRIDE: just because")
    assert o.reason_code == "OVERRIDE"


def test_e4_append_and_read_back(tmp_path):
    path = tmp_path / "overrides.md"
    path.write_text("# Overrides log\n")
    o = parse_override("OVERRIDE: TRAVEL - missed connection")
    append_override(o, path=path)
    content = path.read_text()
    assert "TRAVEL" in content
    assert "missed connection" in content


# --- E5: >2 overrides in a 4-week block -> propose structural revision ----------


def test_e5_two_overrides_in_block_is_fine():
    result = check_override_drift(overrides_in_block=2)
    assert result.allowed


def test_e5_three_overrides_in_block_triggers_structural_flag():
    result = check_override_drift(overrides_in_block=3)
    assert not result.allowed
    assert result.violations[0].rule_id == "E5"
    assert "structural" in result.violations[0].message.lower()


def test_count_overrides_in_window():
    now = datetime(2026, 8, 15, 12, 0, 0)
    overrides = [
        Override(reason_code="TRAVEL", detail="a", logged_at=now - timedelta(days=1)),
        Override(reason_code="SHIN", detail="b", logged_at=now - timedelta(days=10)),
        Override(reason_code="HEAT", detail="c", logged_at=now - timedelta(days=40)),  # outside window
    ]
    count = count_overrides_in_window(overrides, now - timedelta(days=28), now)
    assert count == 2


# --- E2: rolling 3-week compliance shortfall must be surfaced -------------------


def test_e2_below_floor_flags_warning(synthetic_plan):
    build_block = synthetic_plan.blocks["build"]
    result = check_rolling_compliance(0.80, build_block)  # floor is 0.90
    assert not result.allowed
    assert result.violations[0].rule_id == "E2"
    assert "shortfall" in result.violations[0].message.lower()


def test_e2_at_or_above_floor_passes(synthetic_plan):
    build_block = synthetic_plan.blocks["build"]
    result = check_rolling_compliance(0.95, build_block)
    assert result.allowed
