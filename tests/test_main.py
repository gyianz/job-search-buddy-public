from fastapi.testclient import TestClient
import app.main as main
from app.main import create_app
from app.db import connect, get_job, init_db, insert_job, update_status


def make_client(tmp_path):
    db_path = str(tmp_path / "app.db")
    conn = connect(db_path); init_db(conn)
    insert_job(conn, dict(id="j1", source="greenhouse", company="Acme", title="Eng",
                          location="Remote", url="https://x/1", posting_path="jobs/j1/posting.md",
                          fetched_at="2026-11-03T00:00:00"))
    conn.close()
    return TestClient(create_app(
        db_path=db_path, jobs_dir=str(tmp_path / "jobs"),
        seed_path=str(tmp_path / "seed.json"), rubric_path=str(tmp_path / "rubric.json"),
        profile_path=str(tmp_path / "profile.md"),
    ))


def test_dashboard_lists_job(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Acme" in resp.text


def test_dashboard_hides_passed_by_default(tmp_path):
    client = make_client(tmp_path)
    client.post("/job/j1/status", data={"status": "passed"})
    resp = client.get("/")
    assert "Acme" not in resp.text
    resp2 = client.get("/?show_closed=1")
    assert "Acme" in resp2.text


def test_status_rejects_invalid_value(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/job/j1/status", data={"status": "ghosted"})
    assert resp.status_code == 400


def test_job_detail_404_for_missing(tmp_path):
    client = make_client(tmp_path)
    resp = client.get("/job/doesnotexist")
    assert resp.status_code == 404


def test_request_scoring_redirects_and_sets_flag(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/job/j1/request-scoring", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/job/j1"

    db_path = str(tmp_path / "app.db")
    conn = connect(db_path)
    try:
        job = get_job(conn, "j1")
    finally:
        conn.close()
    assert job["needs_scoring"] == 1


def test_request_tailoring_redirects_and_sets_flag(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/job/j1/request-tailoring", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/job/j1"

    db_path = str(tmp_path / "app.db")
    conn = connect(db_path)
    try:
        job = get_job(conn, "j1")
    finally:
        conn.close()
    assert job["needs_tailoring"] == 1


def test_fetch_redirects_and_calls_fetch_all(tmp_path, monkeypatch):
    client = make_client(tmp_path)

    calls = []

    def fake_load_seed():
        return [{"name": "Stub", "platform": "greenhouse", "token": "stub"}]

    def fake_fetch_all(conn, seed):
        calls.append(seed)
        return {"inserted": 0, "errors": []}

    monkeypatch.setattr(main.boards_mod, "load_boards", lambda path=None: fake_load_seed())
    monkeypatch.setattr(main, "fetch_all", fake_fetch_all)

    resp = client.post("/fetch", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/"
    assert calls == [[{"name": "Stub", "platform": "greenhouse", "token": "stub"}]]


def test_create_app_creates_missing_data_directory_and_table(tmp_path):
    # Fresh clone scenario: the parent directory does not exist yet, and
    # no table has been created. create_app() alone must not crash on GET /.
    db_path = str(tmp_path / "nested" / "data" / "app.db")
    client = TestClient(create_app(db_path=db_path))
    resp = client.get("/")
    assert resp.status_code == 200


def test_create_app_honors_jsb_db_path_env_var(tmp_path, monkeypatch):
    db_path = str(tmp_path / "env-configured.db")
    monkeypatch.setenv("JSB_DB_PATH", db_path)
    client = TestClient(create_app())
    resp = client.get("/")
    assert resp.status_code == 200
    import os
    assert os.path.exists(db_path)


def test_status_404_for_missing_job(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/job/doesnotexist/status", data={"status": "applied"})
    assert resp.status_code == 404


def test_request_scoring_404_for_missing_job(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/job/doesnotexist/request-scoring")
    assert resp.status_code == 404


def test_request_tailoring_404_for_missing_job(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/job/doesnotexist/request-tailoring")
    assert resp.status_code == 404


def test_dashboard_renders_board_columns(tmp_path):
    client = make_client(tmp_path)
    client.post("/job/j1/status", data={"status": "applied"})
    resp = client.get("/")
    assert resp.status_code == 200
    for title in ("New", "Interested", "Applied", "Interviewing", "Rejected", "Not interested", "Passed"):
        assert title in resp.text
    # The card sits inside the Applied column.
    applied = resp.text.split('<section class="column" data-status="applied"', 1)[1].split('<section class="column" data-status="interviewing"', 1)[0]
    assert 'data-id="j1"' in applied


def test_status_returns_json_when_requested(tmp_path):
    client = make_client(tmp_path)
    resp = client.post(
        "/job/j1/status",
        data={"status": "interested"},
        headers={"Accept": "application/json"},
        follow_redirects=False,
    )
    assert resp.status_code == 200
    assert resp.json() == {"id": "j1", "status": "interested", "needs_scoring": True}


def test_dashboard_shows_jobs_saved_in_jobs_folder(tmp_path):
    client = make_client(tmp_path)
    folder = tmp_path / "jobs" / "saved1"
    folder.mkdir(parents=True)
    (folder / "posting.md").write_text(
        "# Product Manager\n\n**Company:** Qantas\n**Location:** Adelaide\n"
        "**Source URL:** https://jobs.smartrecruiters.com/QantasGroup/1\n"
    )
    resp = client.get("/")
    assert "Qantas" in resp.text and 'data-id="saved1"' in resp.text


def test_rejected_jobs_stay_on_the_board(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/job/j1/status", data={"status": "rejected"}, follow_redirects=False)
    assert resp.status_code == 303
    board = client.get("/").text
    rejected = board.split('<section class="column" data-status="rejected"', 1)[1].split('<section class="column" data-status="passed"', 1)[0]
    assert 'data-id="j1"' in rejected


def _client_with_folder(tmp_path):
    client = make_client(tmp_path)
    folder = tmp_path / "jobs" / "j1"
    folder.mkdir(parents=True)
    (folder / "posting.md").write_text("# Eng\n\n**Company:** Acme\n**Source URL:** https://x/1\n")
    (folder / "tailored_resume.md").write_text("resume")
    return client


def test_delete_removes_job_and_trashes_folder(tmp_path):
    client = _client_with_folder(tmp_path)
    resp = client.post("/job/j1/delete", follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"] == "/"

    assert not (tmp_path / "jobs" / "j1").exists()
    assert (tmp_path / "jobs" / ".trash" / "j1" / "tailored_resume.md").read_text() == "resume"
    # The folder sync on page load must not bring it back.
    assert 'data-id="j1"' not in client.get("/").text
    assert client.get("/job/j1").status_code == 404


def test_delete_json_and_missing(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/job/j1/delete", headers={"Accept": "application/json"})
    assert resp.json() == {"id": "j1", "deleted": True}
    # No folder existed, but a marker is still left so fetch skips it.
    assert (tmp_path / "jobs" / ".trash" / "j1").is_dir()
    assert client.post("/job/j1/delete").status_code == 404


def _job(tmp_path, job_id="j1"):
    conn = connect(str(tmp_path / "app.db"))
    try:
        return get_job(conn, job_id)
    finally:
        conn.close()


def test_moving_unscored_job_to_interested_requests_scoring(tmp_path):
    client = make_client(tmp_path)
    client.post("/job/j1/status", data={"status": "applied"})
    assert _job(tmp_path)["needs_scoring"] == 0
    client.post("/job/j1/status", data={"status": "interested"})
    assert _job(tmp_path)["needs_scoring"] == 1


def test_moving_scored_job_to_interested_does_not_requeue(tmp_path):
    from app.db import set_score
    client = make_client(tmp_path)
    conn = connect(str(tmp_path / "app.db"))
    set_score(conn, "j1", "match", "fits")
    conn.close()
    resp = client.post("/job/j1/status", data={"status": "interested"},
                       headers={"Accept": "application/json"})
    assert resp.json()["needs_scoring"] is False
    assert _job(tmp_path)["needs_scoring"] == 0


def test_not_interested_column(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/job/j1/status", data={"status": "not_interested"},
                       headers={"Accept": "application/json"})
    assert resp.json()["status"] == "not_interested"
    assert resp.json()["needs_scoring"] is False
    board = client.get("/").text
    column = board.split('<section class="column" data-status="not_interested"', 1)[1].split('<section class="column" data-status="passed"', 1)[0]
    assert 'data-id="j1"' in column


def test_no_fit_jobs_show_label_and_sort_last(tmp_path):
    from app.db import set_score
    client = make_client(tmp_path)
    conn = connect(str(tmp_path / "app.db"))
    insert_job(conn, dict(id="j2", source="greenhouse", company="Beta", title="QA",
                          location="Remote", url="https://x/2", posting_path="jobs/j2/posting.md",
                          fetched_at="2026-11-04T00:00:00"))
    set_score(conn, "j2", "no_fit", "IC QA, no AI angle")
    conn.close()
    board = client.get("/").text
    assert 'lz-no_fit">no fit<' in board
    # j2 is newer, but no-fit sorts below the unscored j1.
    assert board.index('data-id="j1"') < board.index('data-id="j2"')


def test_board_shows_criteria_and_ranks_by_total(tmp_path):
    from app.db import set_score
    client = make_client(tmp_path)
    conn = connect(str(tmp_path / "app.db"))
    insert_job(conn, dict(id="j2", source="greenhouse", company="Beta", title="Lead",
                          location="Remote", url="https://x/2", posting_path="jobs/j2/posting.md",
                          fetched_at="2026-11-01T00:00:00"))
    set_score(conn, "j1", "stretch", "ok", {"change": 2, "skills": 3, "seniority": 3, "salary": 2})
    set_score(conn, "j2", "stretch", "better", {"change": 4, "skills": 5, "seniority": 5, "salary": 4},
              "$175k (est.)")
    conn.close()

    board = client.get("/").text
    assert "18<small>/20</small>" in board and "10<small>/20</small>" in board
    # Same bucket: the higher total (j2) comes first even though j1 is newer.
    assert board.index('data-id="j2"') < board.index('data-id="j1"')

    detail = client.get("/job/j2").text
    assert "18/20" in detail and "$175k (est.)" in detail and "Career direction" in detail


def test_add_job_creates_posting_and_card(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/jobs/add", data={
        "title": "AI Eval Lead", "company": "Gamma", "location": "Adelaide",
        "url": "https://www.linkedin.com/jobs/view/999/", "description": "Build evals.",
    }, headers={"Accept": "application/json"})
    data = resp.json()
    assert data["created"] is True
    text = (tmp_path / "jobs" / data["id"] / "posting.md").read_text()
    assert text.startswith("# AI Eval Lead") and "**Company:** Gamma" in text and "Build evals." in text

    board = client.get("/").text
    new_col = board.split('<section class="column" data-status="new"', 1)[1].split('<section class="column"', 1)[0]
    assert f'data-id="{data["id"]}"' in new_col
    job = _job(tmp_path, data["id"])
    assert job["source"] == "linkedin" and job["status"] == "new"


def test_add_job_into_interested_queues_scoring(tmp_path):
    client = make_client(tmp_path)
    data = client.post("/jobs/add", data={"title": "PM", "company": "Delta", "interested": "true"},
                       headers={"Accept": "application/json"}).json()
    job = _job(tmp_path, data["id"])
    assert job["status"] == "interested" and job["needs_scoring"] == 1
    assert job["url"] == f"local:{data['id']}"


def test_add_job_duplicate_and_validation(tmp_path):
    client = make_client(tmp_path)
    # j1 already tracks https://x/1
    dup = client.post("/jobs/add", data={"title": "Eng", "company": "Acme", "url": "https://x/1"},
                      headers={"Accept": "application/json"})
    assert dup.json() == {"id": "j1", "created": False}
    bad = client.post("/jobs/add", data={"title": " ", "company": "Acme"},
                      headers={"Accept": "application/json"})
    assert bad.status_code == 400
    # Without JS the form redirects to the new job's page.
    resp = client.post("/jobs/add", data={"title": "QA Lead", "company": "Eps"}, follow_redirects=False)
    assert resp.status_code == 303 and resp.headers["location"].startswith("/job/")


def test_lookup_endpoint(tmp_path, monkeypatch):
    client = make_client(tmp_path)
    # Already tracked: answered from the database, no network.
    assert client.get("/jobs/lookup", params={"url": "https://x/1"}).json() == {"existing": "j1"}
    resp = client.get("/jobs/lookup", params={"url": "https://www.linkedin.com/jobs/view/5/"})
    assert resp.status_code == 422 and "LinkedIn" in resp.json()["error"]

    monkeypatch.setattr(main, "lookup_job", lambda url, client: {
        "title": "T", "company": "C", "location": "", "description": "D", "source": "lever"})
    assert client.get("/jobs/lookup", params={"url": "https://jobs.lever.co/c/1"}).json()["title"] == "T"


def _bookmarklet_source(client):
    import html, re
    from urllib.parse import unquote
    page = client.get("/bookmarklet").text
    href = html.unescape(re.search(r'class="drag" href="([^"]+)"', page).group(1))
    assert href.startswith("javascript:")
    return unquote(href[len("javascript:"):])


def test_bookmarklet_points_at_this_server(tmp_path):
    client = make_client(tmp_path)
    source = _bookmarklet_source(client)
    assert 'var APP = "http://testserver";' in source
    assert "/jobs/new#" in source
    # Never makes network requests itself; it only opens the board.
    assert "fetch(" not in source and "XMLHttpRequest" not in source


def test_bookmarklet_is_valid_javascript(tmp_path):
    import shutil, subprocess
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node not installed")
    source = _bookmarklet_source(make_client(tmp_path))
    result = subprocess.run([node, "--check", "-"], input=source, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_new_job_page_renders_form(tmp_path):
    client = make_client(tmp_path)
    page = client.get("/jobs/new").text
    assert 'action="/jobs/add"' in page and 'name="description"' in page
    assert "Back to board" in page and 'id="lookup-btn"' not in page
    assert '<option value="Acme">' in page


def test_interviewing_column(tmp_path):
    client = make_client(tmp_path)
    resp = client.post("/job/j1/status", data={"status": "interviewing"},
                       headers={"Accept": "application/json"})
    assert resp.json()["status"] == "interviewing" and resp.json()["needs_scoring"] is False
    board = client.get("/").text
    column = board.split('<section class="column" data-status="interviewing"', 1)[1].split('<section class="column"', 1)[0]
    assert 'data-id="j1"' in column
    assert 'value="interviewing" selected' in client.get("/job/j1").text


def test_board_css_lets_filters_hide_cards(tmp_path):
    # Filters hide cards with the hidden attribute; .card sets display: block,
    # so the page must force [hidden] to display: none or nothing disappears.
    board = make_client(tmp_path).get("/").text
    assert "[hidden] { display: none !important; }" in board


def _client_with_docs(tmp_path):
    client = make_client(tmp_path)
    conn = connect(str(tmp_path / "app.db"))
    insert_job(conn, dict(id="abc123def456", source="manual", company="Acme", title="AI Eval Lead",
                          location="Remote", url="https://x/docs", posting_path="p",
                          fetched_at="2026-11-04T00:00:00"))
    conn.close()
    folder = tmp_path / "jobs" / "abc123def456"
    folder.mkdir(parents=True)
    (folder / "tailored_resume.md").write_text("# Jane Doe\n\n## Experience\n\n- Built **evals**\n")
    (folder / "tailored_resume.pdf").write_bytes(b"%PDF-1.4 fake")
    (folder / "cover_letter.pdf").write_bytes(b"%PDF-1.4 letter")
    (folder / "notes.txt").write_text("private")
    return client


def test_job_page_shows_tailored_documents(tmp_path):
    page = _client_with_docs(tmp_path).get("/job/abc123def456").text
    assert 'data-tab="resume"' in page and 'data-tab="cover-letter"' in page
    assert "<strong>evals</strong>" in page  # resume markdown is rendered
    assert "View tailored resume" in page and "View cover letter" in page
    # Cover letter only exists as a PDF, so it's embedded.
    assert '<iframe class="pdf-frame" src="/job/abc123def456/docs/cover_letter.pdf"' in page


def test_job_page_without_documents_has_only_description(tmp_path):
    page = make_client(tmp_path).get("/job/j1").text
    assert 'data-tab="resume"' not in page and "View tailored resume" not in page


def test_document_route_serves_pdf_and_markdown(tmp_path):
    client = _client_with_docs(tmp_path)
    pdf = client.get("/job/abc123def456/docs/tailored_resume.pdf")
    assert pdf.status_code == 200 and pdf.content == b"%PDF-1.4 fake"
    assert pdf.headers["content-type"] == "application/pdf"
    assert pdf.headers["content-disposition"].startswith("inline")
    md = client.get("/job/abc123def456/docs/tailored_resume.md?download=1")
    assert md.text.startswith("# Jane Doe")
    assert md.headers["content-disposition"].startswith("attachment")
    from urllib.parse import unquote
    assert "Tailored resume - Acme - AI Eval Lead.md" in unquote(md.headers["content-disposition"])


def test_document_route_only_serves_known_files(tmp_path):
    client = _client_with_docs(tmp_path)
    for url in ("/job/abc123def456/docs/notes.txt",
                "/job/abc123def456/docs/cover_letter.md",  # allowed name, but missing
                "/job/..%2F..%2Fetc/docs/tailored_resume.md",
                "/job/abc123def456/docs/..%2F..%2Fapp.db"):
        assert client.get(url).status_code == 404, url
