import pytest

from mc import export


@pytest.fixture
def out_dir(tmp_path):
    d = tmp_path / "out"
    d.mkdir()
    (d / "today.md").write_text("# 02-08 · Week 1/14\n")
    (d / "today.html").write_text("<h1>today</h1>")
    (d / "dashboard.html").write_text("<h1>dashboard</h1>")
    return d


# --- opt-in behaviour --------------------------------------------------------------


def test_unset_env_var_disables_export(monkeypatch, out_dir):
    monkeypatch.delenv("MC_EXPORT_DIR", raising=False)
    result = export.export(out_dir=out_dir)
    assert not result.enabled
    assert result.copied == []


def test_blank_env_var_disables_export(monkeypatch):
    monkeypatch.setenv("MC_EXPORT_DIR", "   ")
    assert export.export_dir() is None


def test_env_var_expands_user(monkeypatch):
    monkeypatch.setenv("MC_EXPORT_DIR", "~/marathon-export")
    assert "~" not in str(export.export_dir())


# --- copying -----------------------------------------------------------------------


def test_copies_html_and_today_md(tmp_path, out_dir):
    dest = tmp_path / "synced" / "marathon"
    dest.parent.mkdir()
    result = export.export(out_dir=out_dir, destination=dest)
    names = {p.name for p in result.copied}
    assert names == {"today.md", "today.html", "dashboard.html"}
    assert (dest / "today.html").read_text() == "<h1>today</h1>"


def test_creates_leaf_directory_but_not_parents(tmp_path, out_dir):
    dest = tmp_path / "synced" / "marathon"
    dest.parent.mkdir()
    assert not dest.exists()
    export.export(out_dir=out_dir, destination=dest)
    assert dest.is_dir()


def test_missing_parent_raises_rather_than_creating_a_stray_tree(tmp_path, out_dir):
    """A missing parent means the sync root isn't mounted. Creating it anyway
    would report success every day while the phone showed nothing."""
    dest = tmp_path / "not-mounted" / "marathon"
    with pytest.raises(export.ExportError, match="never sync"):
        export.export(out_dir=out_dir, destination=dest)
    assert not dest.exists()


def test_overwrites_previous_export(tmp_path, out_dir):
    dest = tmp_path / "synced"
    export.export(out_dir=out_dir, destination=dest)
    (out_dir / "today.html").write_text("<h1>updated</h1>")
    export.export(out_dir=out_dir, destination=dest)
    assert (dest / "today.html").read_text() == "<h1>updated</h1>"


def test_missing_out_dir_is_not_an_error(tmp_path):
    dest = tmp_path / "synced"
    result = export.export(out_dir=tmp_path / "nonexistent", destination=dest)
    assert result.enabled
    assert result.copied == []


def test_never_exports_logs_or_data(tmp_path, out_dir):
    """Only rendered artifacts leave the repo — the audit trail syncs via git,
    where conflicts fail loudly instead of being silently resolved."""
    (out_dir / "training-log.txt").write_text("private")
    (out_dir / "notes.json").write_text("{}")
    result = export.export(out_dir=out_dir, destination=tmp_path / "synced")
    assert not any(p.suffix in {".txt", ".json"} for p in result.copied)
