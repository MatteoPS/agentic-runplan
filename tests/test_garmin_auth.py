"""The headless-auth path.

The bug this covers: nothing in the CLI ever asked for the non-interactive
path, so on a machine with an expired token `mc sync` called input(), hit a
closed stdin, and died with a bare EOFError traceback — while a perfectly
clear GarminAuthError for exactly this situation already existed and was
never reached.
"""

import io

import pytest

from mc import garmin


# --- detection ----------------------------------------------------------------------


def test_no_tty_is_detected_as_non_interactive(monkeypatch):
    monkeypatch.setattr("sys.stdin", io.StringIO(""))  # StringIO.isatty() is False
    assert garmin.is_interactive() is False


def test_a_tty_is_detected_as_interactive(monkeypatch):
    class FakeTTY:
        def isatty(self):
            return True

    monkeypatch.setattr("sys.stdin", FakeTTY())
    assert garmin.is_interactive() is True


def test_detached_stdin_is_non_interactive(monkeypatch):
    """sys.stdin can be None under pythonw / some launchers, and isatty() on a
    closed file raises ValueError. Neither should crash the detection."""
    monkeypatch.setattr("sys.stdin", None)
    assert garmin.is_interactive() is False

    class ClosedStdin:
        def isatty(self):
            raise ValueError("I/O operation on closed file")

    monkeypatch.setattr("sys.stdin", ClosedStdin())
    assert garmin.is_interactive() is False


# --- the prompts ----------------------------------------------------------------------


def test_unavailable_prompt_raises_a_clear_auth_error():
    with pytest.raises(garmin.GarminAuthError) as exc:
        garmin._prompt_mfa_unavailable()
    assert "no terminal" in str(exc.value)
    assert "mc sync" in str(exc.value)  # tells you what to actually run


def test_interactive_prompt_converts_eoferror(monkeypatch):
    """isatty() can be True and the read still fail — stdin closed mid-run, a
    wrapper faking a tty, or Ctrl-D at the prompt. Must not surface as a bare
    EOFError traceback."""
    def boom(*_a, **_k):
        raise EOFError

    monkeypatch.setattr("builtins.input", boom)
    with pytest.raises(garmin.GarminAuthError):
        garmin._prompt_mfa_interactive()


def test_interactive_prompt_converts_keyboard_interrupt(monkeypatch):
    def boom(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr("builtins.input", boom)
    with pytest.raises(garmin.GarminAuthError):
        garmin._prompt_mfa_interactive()


def test_interactive_prompt_returns_a_stripped_code(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda *_a, **_k: "  123456  ")
    assert garmin._prompt_mfa_interactive() == "123456"


# --- wiring: get_client picks the right prompt ----------------------------------------


@pytest.fixture
def captured_prompt(monkeypatch, tmp_path):
    """Capture the prompt_mfa callable get_client hands to Garmin, without
    touching the network."""
    monkeypatch.setattr(garmin.cfg, "GARMIN_TOKENS_DIR", tmp_path / "tokens")
    seen = {}

    class FakeGarmin:
        def __init__(self, **kwargs):
            seen["prompt_mfa"] = kwargs.get("prompt_mfa")

        def login(self, **_kwargs):
            return None

    monkeypatch.setattr(garmin, "Garmin", FakeGarmin)
    return seen


def test_headless_run_gets_the_failing_prompt_without_any_flag(monkeypatch, captured_prompt):
    """The regression that matters: a cloud session passes no flags at all."""
    monkeypatch.setattr("sys.stdin", io.StringIO(""))
    garmin.get_client()
    assert captured_prompt["prompt_mfa"] is garmin._prompt_mfa_unavailable


def test_terminal_run_still_gets_the_real_prompt(monkeypatch, captured_prompt):
    monkeypatch.setattr(garmin, "is_interactive", lambda: True)
    garmin.get_client()
    assert captured_prompt["prompt_mfa"] is garmin._prompt_mfa_interactive


def test_explicit_argument_overrides_detection(monkeypatch, captured_prompt):
    monkeypatch.setattr(garmin, "is_interactive", lambda: True)
    garmin.get_client(interactive=False)
    assert captured_prompt["prompt_mfa"] is garmin._prompt_mfa_unavailable

    monkeypatch.setattr(garmin, "is_interactive", lambda: False)
    garmin.get_client(interactive=True)
    assert captured_prompt["prompt_mfa"] is garmin._prompt_mfa_interactive


# --- the whole way up through mc sync -------------------------------------------------


def test_sync_reports_an_auth_failure_instead_of_crashing(monkeypatch):
    """GarminAuthError must land in the source report as a clean ok=False, so
    /daily's step 1 sees `ok: false` and says the data didn't arrive (§7),
    rather than the process dying mid-run."""
    from mc import sync as sync_mod

    def raise_auth(*_a, **_k):
        raise garmin.GarminAuthError("Garmin wants an MFA code, but there's no terminal")

    monkeypatch.setattr(sync_mod.garmin, "sync_garmin", raise_auth)
    report = sync_mod.run_sync(source="garmin", interactive=False)

    assert not report.all_ok
    assert report.sources["garmin"].ok is False
    assert "MFA" in report.sources["garmin"].error
