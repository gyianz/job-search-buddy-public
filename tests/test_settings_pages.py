import json
import re
import sqlite3

from fastapi.testclient import TestClient

from app.cli import main as cli_main
from app.db import connect, get_job, init_db, insert_job, set_score
from app.main import create_app
from app.markdown import render
from app.rubric import DEFAULT_RUBRIC, load_rubric


def make_client(tmp_path, profile="# Me, Profile\n\n## Skills\n\n- Python\n- **Evals**\n"):
    (tmp_path / "profile.md").write_text(profile)
    (tmp_path / "seed.json").write_text(json.dumps([
        {"name": "Acme", "platform": "greenhouse", "token": "acme", "title_keywords": ["qa"]},
    ]))
    db_path = str(tmp_path / "app.db")
    conn = connect(db_path); init_db(conn)
    insert_job(conn, dict(id="j1", source="greenhouse", company="Acme", title="Eng",
                          location="Remote", url="https://x/1", posting_path="p",
                          fetched_at="2026-11-03T00:00:00"))
    conn.close()
    return TestClient(create_app(
        db_path=db_path, jobs_dir=str(tmp_path / "jobs"),
        seed_path=str(tmp_path / "seed.json"), rubric_path=str(tmp_path / "rubric.json"),
        profile_path=str(tmp_path / "profile.md"),
    ))


# ---- Profile -------------------------------------------------------------

def test_profile_page_renders_sections(tmp_path):
    text = make_client(tmp_path).get("/profile").text
    assert "Me, Profile" in text and "<strong>Evals</strong>" in text and "2 items" in text


def test_profile_page_hides_scoring_rubric_section(tmp_path):
    client = make_client(tmp_path, "# P\n\n## Skills\n\n- a\n\n## Scoring Rubric\n\nSECRET-RULES\n")
    assert "SECRET-RULES" not in client.get("/profile").text


def test_markdown_escapes_html():
    assert "<script>" not in render("- <script>alert(1)</script>")


def test_markdown_tables_and_wrapped_bullets():
    out = render("| a | b |\n|---|---|\n| 1 | 2 |\n\n- one\n  continued\n- two")
    assert "<td>1</td>" in out and "<li>one continued</li>" in out


# ---- Job boards -----------------------------------------------------------

def test_boards_page_counts_connections(tmp_path):
    text = make_client(tmp_path).get("/boards").text
    assert "Acme" in text and "1 job" in text and "connection" in text


def test_add_and_remove_board(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/boards/add", data={
        "name": "Canva", "platform": "lever", "token": "canva",
        "title_keywords": "quality, ml ", "location_keywords": "",
    }, follow_redirects=False)
    assert resp.status_code == 303 and "added=Canva" in resp.headers["location"]
    seed = json.loads((tmp_path / "seed.json").read_text())
    assert seed[-1] == {"name": "Canva", "platform": "lever", "token": "canva",
                        "title_keywords": ["quality", "ml "]}

    dup = client.post("/boards/add", data={"name": "x", "platform": "lever", "token": "canva"},
                      follow_redirects=False)
    assert "error=" in dup.headers["location"]

    client.post("/boards/remove", data={"platform": "lever", "token": "canva"})
    assert [b["name"] for b in json.loads((tmp_path / "seed.json").read_text())] == ["Acme"]


def test_add_board_rejects_unknown_platform(tmp_path):
    resp = make_client(tmp_path).post("/boards/add", data={
        "name": "X", "platform": "workday", "token": "x"}, follow_redirects=False)
    assert "error=" in resp.headers["location"]


def test_board_test_reports_matching_postings(tmp_path, monkeypatch):
    import app.main as main
    monkeypatch.setitem(main.FETCHERS, "greenhouse", lambda token, client: [
        {"title": "QA Lead", "url": "u1", "location": "Sydney"},
        {"title": "Designer", "url": "u2", "location": "Sydney"},
    ])
    data = make_client(tmp_path).get(
        "/boards/test", params={"platform": "greenhouse", "token": "acme", "title_keywords": "qa"}
    ).json()
    assert data == {"total": 2, "matching": 1, "sample": ["QA Lead"]}


# ---- Rubric ---------------------------------------------------------------

def test_rubric_page_shows_default_rules_and_criteria(tmp_path):
    text = make_client(tmp_path).get("/rubric").text
    assert "Wrong location" in text and "Career direction" in text and "out of 20" in text


def test_add_and_remove_rule(tmp_path):
    client = make_client(tmp_path)
    client.post("/rubric/rules/deal_breakers/add",
                data={"title": "Needs security clearance", "detail": "NV1 or above"})
    rubric = load_rubric(tmp_path / "rubric.json")
    assert rubric["deal_breakers"][-1] == {"title": "Needs security clearance", "detail": "NV1 or above"}

    index = len(rubric["deal_breakers"]) - 1
    stale = client.post("/rubric/rules/deal_breakers/remove",
                        data={"index": 0, "title": "Needs security clearance"}, follow_redirects=False)
    assert "error=" in stale.headers["location"]
    client.post("/rubric/rules/deal_breakers/remove",
                data={"index": index, "title": "Needs security clearance"})
    assert "Needs security clearance" not in json.dumps(load_rubric(tmp_path / "rubric.json"))


def _criterion(key="stability", **extra):
    return {"key": key, "label": "Company stability", "short": "Stb", "description": "d",
            "level5": "a", "level4": "b", "level3": "c", "level2": "d", "level1": "e", **extra}


def test_add_criterion_changes_totals_and_requeue(tmp_path):
    client = make_client(tmp_path)
    conn = connect(str(tmp_path / "app.db"))
    set_score(conn, "j1", "match", "ok", {"change": 3, "skills": 4, "seniority": 5, "salary": 4})
    conn.close()
    assert "16<small>/20</small>" in client.get("/").text

    client.post("/rubric/criteria/add", data=_criterion())
    board = client.get("/").text
    assert "16<small>/25</small>" in board and "Company stability: not scored yet" in board
    assert "1</strong> of 1 scored job" in client.get("/rubric").text

    client.post("/rubric/requeue")
    conn = connect(str(tmp_path / "app.db"))
    assert get_job(conn, "j1")["needs_scoring"] == 1
    conn.close()

    client.post("/rubric/criteria/change/remove")
    assert "13<small>/20</small>" in client.get("/").text


def test_add_criterion_validates_and_keeps_input(tmp_path):
    client = make_client(tmp_path)
    for bad in (_criterion("Bad Key"), _criterion("change"), _criterion(level3="")):
        resp = client.post("/rubric/criteria/add", data=bad, follow_redirects=False)
        assert resp.status_code == 400
        # The form comes back open, with the error and what was typed.
        assert 'id="add-criterion" open' in resp.text and 'class="form-error"' in resp.text
        assert 'value="Company stability"' in resp.text and 'value="a"' in resp.text
    assert [c["key"] for c in load_rubric(tmp_path / "rubric.json")["criteria"]] == [
        "change", "skills", "seniority", "salary"]


def test_add_rule_error_keeps_input_in_its_form(tmp_path):
    resp = make_client(tmp_path).post(
        "/rubric/rules/match_families/add", data={"title": "  ", "detail": "my notes"})
    assert resp.status_code == 400
    assert 'id="add-match_families" open' in resp.text and "my notes</textarea>" in resp.text


def test_add_redirects_to_and_highlights_new_item(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/rubric/rules/stretch_examples/add", data={"title": "Data eng"},
                       follow_redirects=False)
    new = f"rule-stretch_examples-{len(DEFAULT_RUBRIC['stretch_examples'])}"
    assert resp.headers["location"].endswith("#" + new)
    page = client.get(resp.headers["location"]).text
    assert re.search(rf'id="{new}" class="editable just-added', page)

    resp = client.post("/rubric/criteria/add", data=_criterion(), follow_redirects=False)
    assert resp.headers["location"].endswith("#crit-stability")


def test_cli_score_accepts_custom_criterion(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JSB_DB_PATH", str(tmp_path / "app.db"))
    monkeypatch.setenv("JSB_RUBRIC_PATH", str(tmp_path / "rubric.json"))
    make_client(tmp_path).post("/rubric/criteria/add", data=_criterion())
    assert cli_main(["score", "j1", "match", "--stability", "4", "--skills", "5", "fits"]) == 0
    conn = connect(str(tmp_path / "app.db"))
    assert get_job(conn, "j1")["criteria_scores"] == {"stability": 4, "skills": 5}
    conn.close()
    assert cli_main(["rubric"]) == 0
    assert "Company stability (`--stability`)" in capsys.readouterr().out


def test_legacy_score_columns_migrate(tmp_path):
    path = str(tmp_path / "old.db")
    conn = connect(path); init_db(conn)
    insert_job(conn, dict(id="a", source="gh", company="A", title="T", location=None,
                          url="u", posting_path="p", fetched_at="2026-01-01"))
    conn.execute("UPDATE jobs SET change_score = 4, salary_score = 2 WHERE id = 'a'")
    conn.commit()
    init_db(conn)
    assert get_job(conn, "a")["criteria_scores"] == {"change": 4, "salary": 2}
    conn.close()


# ---- Editing the rubric -----------------------------------------------------

def test_edit_rule(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/rubric/rules/deal_breakers/0/edit", data={
        "original_title": "Fixed-term or contract", "title": "Contract roles",
        "detail": "Unless 12+ months"}, follow_redirects=False)
    assert resp.headers["location"].endswith("#rule-deal_breakers-0")
    assert load_rubric(tmp_path / "rubric.json")["deal_breakers"][0] == {
        "title": "Contract roles", "detail": "Unless 12+ months"}


def test_edit_rule_refuses_stale_title_and_keeps_input_on_error(tmp_path):
    client = make_client(tmp_path)
    stale = client.post("/rubric/rules/deal_breakers/0/edit", data={
        "original_title": "Something else", "title": "X"})
    assert stale.status_code == 409
    empty = client.post("/rubric/rules/deal_breakers/0/edit", data={
        "original_title": "Fixed-term or contract", "title": " ", "detail": "kept text"})
    assert empty.status_code == 400 and "editable  editing" in empty.text and "kept text</textarea>" in empty.text
    assert load_rubric(tmp_path / "rubric.json")["deal_breakers"][0]["title"] == "Fixed-term or contract"


def test_edit_criterion_keeps_key_and_scores(tmp_path):
    client = make_client(tmp_path)
    conn = connect(str(tmp_path / "app.db"))
    set_score(conn, "j1", "match", "ok", {"change": 3, "skills": 4, "seniority": 5, "salary": 4})
    conn.close()
    data = {"label": "Salary (base)", "short": "$", "description": "d", "notes": "",
            "level5": "200k+", "level4": "b", "level3": "c", "level2": "d", "level1": "e"}
    resp = client.post("/rubric/criteria/salary/edit", data=data, follow_redirects=False)
    assert resp.headers["location"].endswith("#crit-salary")
    crit = load_rubric(tmp_path / "rubric.json")["criteria"][-1]
    assert crit["key"] == "salary" and crit["label"] == "Salary (base)" and crit["levels"][0] == "200k+"
    assert "16<small>/20</small>" in client.get("/").text

    bad = client.post("/rubric/criteria/salary/edit", data={**data, "level2": ""})
    assert bad.status_code == 400 and 'value="200k+"' in bad.text


def test_edit_rationale_guide(tmp_path):
    client = make_client(tmp_path)
    client.post("/rubric/rationale", data={"rationale_guide": "One **short** paragraph.\r\n"})
    assert load_rubric(tmp_path / "rubric.json")["rationale_guide"] == "One **short** paragraph."
    assert "<strong>short</strong>" in client.get("/rubric").text


# ---- Editing the profile ----------------------------------------------------

PROFILE = """# Me, Profile

Intro line.

## Skills

- Python
- Evals

## Experience

**Eng, Acme** (2020 - 2024)
- Built things

## Scoring Rubric

Pointer.
"""


def _version(client):
    return re.search(r'name="version" value="([0-9a-f]+)"', client.get("/profile").text).group(1)


def test_edit_profile_section_only_changes_that_section(tmp_path):
    client = make_client(tmp_path, PROFILE)
    resp = client.post("/profile/sections/0/edit", data={
        "version": _version(client), "title": "Core skills", "body": "- Python\r\n- LLM evals\r\n"},
        follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"].endswith("#core-skills")
    assert (tmp_path / "profile.md").read_text() == PROFILE.replace(
        "## Skills\n\n- Python\n- Evals", "## Core skills\n\n- Python\n- LLM evals")


def test_profile_edit_conflict_keeps_user_text(tmp_path):
    client = make_client(tmp_path, PROFILE)
    version = _version(client)
    (tmp_path / "profile.md").write_text(PROFILE + "\nAppended by Claude.\n")
    resp = client.post("/profile/sections/0/edit", data={
        "version": version, "title": "Skills", "body": "- my unsaved edit"})
    assert resp.status_code == 409 and "my unsaved edit" in resp.text and "changed since you opened it" in resp.text
    assert "Appended by Claude." in (tmp_path / "profile.md").read_text()


def test_add_and_delete_profile_section(tmp_path):
    client = make_client(tmp_path, PROFILE)
    client.post("/profile/sections/add", data={
        "version": _version(client), "title": "Certifications", "body": "- ISTQB"})
    text = (tmp_path / "profile.md").read_text()
    # New sections go before the Scoring Rubric pointer, which stays last.
    assert text.index("## Certifications") < text.index("## Scoring Rubric")
    assert "Certifications" in client.get("/profile").text

    client.post("/profile/sections/2/delete", data={"version": _version(client)})
    assert "## Certifications" not in (tmp_path / "profile.md").read_text()
    assert "## Scoring Rubric" in (tmp_path / "profile.md").read_text()


def test_save_whole_profile(tmp_path):
    client = make_client(tmp_path, PROFILE)
    client.post("/profile/save", data={"version": _version(client), "text": "# New\r\n\r\n## A\r\n\r\nB"})
    assert (tmp_path / "profile.md").read_text() == "# New\n\n## A\n\nB\n"


def test_profile_section_titles_ignore_fenced_code():
    from app.profile import sections
    assert [s["title"] for s in sections("## A\n```\n## not a heading\n```\n## B\n")] == ["A", "B"]
