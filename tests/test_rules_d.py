from mc.rules import SymptomReport, check_safety


def test_no_symptoms_allows_running():
    result = check_safety(SymptomReport())
    assert result.allow_running
    assert not result.see_professional


# --- D1: shin pain ---------------------------------------------------------------


def test_d1_sharp_shin_pain_blocks_running():
    result = check_safety(SymptomReport(shin_pain="sharp"))
    assert not result.allow_running
    assert result.see_professional
    assert any("professional" in m.lower() for m in result.messages)


def test_d1_localized_bone_pain_blocks_running():
    result = check_safety(SymptomReport(shin_pain="localized_bone"))
    assert not result.allow_running


def test_d1_worsens_during_run_blocks_running():
    result = check_safety(SymptomReport(shin_pain="worsens_during_run"))
    assert not result.allow_running


def test_d1_dull_shin_pain_does_not_block_running():
    result = check_safety(SymptomReport(shin_pain="dull"))
    assert result.allow_running


def test_d1_offers_elliptical_only_if_pain_free():
    blocked_but_ok_elliptical = check_safety(
        SymptomReport(shin_pain="sharp", shin_pain_free_on_elliptical=True)
    )
    assert blocked_but_ok_elliptical.allow_elliptical

    blocked_and_not_ok_elliptical = check_safety(
        SymptomReport(shin_pain="sharp", shin_pain_free_on_elliptical=False)
    )
    assert not blocked_and_not_ok_elliptical.allow_elliptical


# --- D2: gait-altering pain -------------------------------------------------------


def test_d2_gait_altering_pain_blocks_running():
    result = check_safety(SymptomReport(gait_altering_pain=True))
    assert not result.allow_running


# --- D3: posterior thigh / sit-bone pain (hamstring signal) ----------------------


def test_d3_hamstring_signal_does_not_block_running_but_constrains_it():
    result = check_safety(SymptomReport(posterior_thigh_or_sitbone_pain=True))
    assert result.allow_running  # not a hard stop
    assert result.no_speed
    assert result.no_hills
    assert result.no_long_stride
    assert any("hamstring" in m.lower() for m in result.messages)


# --- D4: 3 consecutive low self-reports -------------------------------------------


def test_d4_three_consecutive_low_reports_flags_recovery_week():
    result = check_safety(SymptomReport(recent_self_reports=[7, 3, 2, 3]))
    assert result.propose_recovery_week


def test_d4_two_consecutive_low_reports_does_not_flag():
    result = check_safety(SymptomReport(recent_self_reports=[7, 3, 3]))
    assert not result.propose_recovery_week


def test_d4_low_reports_not_consecutive_does_not_flag():
    result = check_safety(SymptomReport(recent_self_reports=[3, 7, 3, 3]))
    assert not result.propose_recovery_week


# --- D5: fever / illness -----------------------------------------------------------


def test_d5_fever_blocks_running():
    result = check_safety(SymptomReport(fever_or_illness=True))
    assert not result.allow_running


# --- D6: not a doctor, always surfaced when relevant ------------------------------


def test_d6_disclaimer_present_when_stop_triggered():
    result = check_safety(SymptomReport(gait_altering_pain=True))
    assert any("not a doctor" in m.lower() for m in result.messages)


def test_d6_disclaimer_absent_when_nothing_wrong():
    result = check_safety(SymptomReport())
    assert not any("not a doctor" in m.lower() for m in result.messages)


# --- combined scenario -------------------------------------------------------------


def test_multiple_d_signals_combine():
    result = check_safety(
        SymptomReport(
            shin_pain="sharp",
            posterior_thigh_or_sitbone_pain=True,
            fever_or_illness=True,
        )
    )
    assert not result.allow_running
    assert result.see_professional
    assert result.no_speed
    assert len(result.messages) >= 4  # D1, D3, D5, D6 all present
