from datetime import date

from mc import render


def test_headers():
    html = render.markdown_to_html_body("# Title\n## Sub")
    assert "<h1>Title</h1>" in html
    assert "<h2>Sub</h2>" in html


def test_bold_italic_code_link():
    html = render.markdown_to_html_body("**bold** *italic* `code` [link](http://x.test)")
    assert "<strong>bold</strong>" in html
    assert "<em>italic</em>" in html
    assert "<code>code</code>" in html
    assert '<a href="http://x.test">link</a>' in html


def test_table():
    md = "| A | B |\n|---|---|\n| 1 | 2 |\n"
    html = render.markdown_to_html_body(md)
    assert "<table>" in html and "</table>" in html
    assert "<th>A</th>" in html
    assert "<td>1</td>" in html


def test_unordered_list():
    html = render.markdown_to_html_body("- one\n- two\n")
    assert html.count("<li>") == 2
    assert "<ul>" in html and "</ul>" in html


def test_blockquote():
    html = render.markdown_to_html_body("> a warning")
    assert "<blockquote>a warning</blockquote>" in html


def test_horizontal_rule():
    html = render.markdown_to_html_body("above\n\n---\n\nbelow")
    assert "<hr>" in html


def test_paragraph_and_html_escaping():
    html = render.markdown_to_html_body("5 < 10 & fine")
    assert "&lt;" in html and "&amp;" in html


def test_full_page_has_title_and_style():
    page = render.render_markdown("# My Title\n\nsome text")
    assert "<title>My Title</title>" in page
    assert "<style>" in page
    assert "<!doctype html>" in page.lower()


def test_render_file_writes_html_twin(tmp_path):
    md_path = tmp_path / "today.md"
    md_path.write_text("# Today\n\n- easy run\n")
    html_path = render.render_file(md_path)
    assert html_path == tmp_path / "today.html"
    assert html_path.exists()
    assert "<h1>Today</h1>" in html_path.read_text()


def test_render_all_finds_every_md(tmp_path):
    (tmp_path / "today.md").write_text("# A")
    (tmp_path / "week-01.md").write_text("# B")
    rendered = render.render_all(out_dir=tmp_path)
    assert len(rendered) == 2
    assert {p.name for p in rendered} == {"today.html", "week-01.html"}


def test_render_all_empty_dir_returns_empty(tmp_path):
    assert render.render_all(out_dir=tmp_path / "nonexistent") == []


# --- dashboard ----------------------------------------------------------------


def test_dashboard_weeks_to_race(synthetic_plan):
    html = render.build_dashboard_html(synthetic_plan, [], as_of=date(2026, 7, 27))
    days_to_race = (synthetic_plan.race_date - date(2026, 7, 27)).days
    assert str(days_to_race // 7) in html


def test_dashboard_flags_travel_block(synthetic_plan):
    html = render.build_dashboard_html(synthetic_plan, [], as_of=date(2026, 7, 27))
    assert "24-08" in html  # travel_italy week 5's w/c date


def test_dashboard_future_weeks_show_dashes(synthetic_plan):
    html = render.build_dashboard_html(synthetic_plan, [], as_of=date(2026, 7, 27))
    assert "—" in html  # weeks after week 1 haven't started yet


def test_dashboard_is_valid_page(synthetic_plan):
    html = render.build_dashboard_html(synthetic_plan, [], as_of=date(2026, 7, 27))
    assert "<!doctype html>" in html.lower()
    assert html.count("<table>") == html.count("</table>")
