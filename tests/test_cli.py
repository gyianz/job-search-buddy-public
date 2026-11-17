import pytest
from app.db import connect, init_db, insert_job, set_needs_scoring
from app.cli import main


def setup_job(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("JSB_DB_PATH", str(tmp_path / "app.db"))


def test_pending_lists_flagged_jobs(tmp_path, monkeypatch, capsys):
    setup_job(tmp_path, monkeypatch)
    from app.db import connect as c
    conn = c(str(tmp_path / "app.db")); init_db(conn)
    insert_job(conn, dict(id="j1", source="greenhouse", company="Acme", title="Eng",
                          location="Remote", url="https://x/1", posting_path="jobs/j1/posting.md",
                          fetched_at="2026-11-03T00:00:00"))
    set_needs_scoring(conn, "j1")
    conn.close()
    assert main(["pending"]) == 0
    out = capsys.readouterr().out
    assert "j1" in out and "needs_scoring" in out


def test_score_rejects_unknown_bucket(tmp_path, monkeypatch, capsys):
    setup_job(tmp_path, monkeypatch)
    assert main(["score", "j1", "maybe", "reason"]) == 1


def test_score_rejects_missing_job_id(tmp_path, monkeypatch, capsys):
    setup_job(tmp_path, monkeypatch)
    assert main(["score", "does-not-exist", "match", "reason"]) == 1
    out = capsys.readouterr().out
    assert "error" in out.lower()


def test_tailor_rejects_missing_job_id(tmp_path, monkeypatch, capsys):
    setup_job(tmp_path, monkeypatch)
    assert main(["tailor", "does-not-exist", "resume.md", "cover.md"]) == 1
    out = capsys.readouterr().out
    assert "error" in out.lower()


def test_add_inserts_new_job(tmp_path, monkeypatch, capsys):
    setup_job(tmp_path, monkeypatch)
    assert main(["add", "Acme", "Engineer", "https://acme.example/jobs/1", "Remote"]) == 0
    out = capsys.readouterr().out
    assert "inserted" in out

    conn = connect(str(tmp_path / "app.db"))
    jobs = [dict(row) for row in conn.execute("SELECT * FROM jobs").fetchall()]
    conn.close()
    assert len(jobs) == 1
    assert jobs[0]["company"] == "Acme"
    assert jobs[0]["title"] == "Engineer"
    assert jobs[0]["source"] == "manual"
    assert jobs[0]["location"] == "Remote"


def test_add_reports_duplicate(tmp_path, monkeypatch, capsys):
    setup_job(tmp_path, monkeypatch)
    url = "https://acme.example/jobs/1"
    assert main(["add", "Acme", "Engineer", url]) == 0
    capsys.readouterr()
    assert main(["add", "Acme", "Engineer", url]) == 0
    out = capsys.readouterr().out
    assert "duplicate" in out


def test_score_accepts_no_fit(tmp_path, monkeypatch, capsys):
    setup_job(tmp_path, monkeypatch)
    from app.db import connect, get_job, init_db, insert_job
    conn = connect(str(tmp_path / "app.db")); init_db(conn)
    insert_job(conn, dict(id="j1", source="greenhouse", company="Acme", title="Eng",
                          location="Remote", url="https://x/1", posting_path="jobs/j1/posting.md",
                          fetched_at="2026-11-03T00:00:00"))
    conn.close()
    assert main(["score", "j1", "no_fit", "fixed-term contract"]) == 0
    conn = connect(str(tmp_path / "app.db"))
    job = get_job(conn, "j1")
    conn.close()
    assert job["score_bucket"] == "no_fit"
    assert job["needs_scoring"] == 0


def _seed_j1(tmp_path):
    from app.db import connect, init_db, insert_job
    conn = connect(str(tmp_path / "app.db")); init_db(conn)
    insert_job(conn, dict(id="j1", source="greenhouse", company="Acme", title="Eng",
                          location="Remote", url="https://x/1", posting_path="jobs/j1/posting.md",
                          fetched_at="2026-11-03T00:00:00"))
    conn.close()


def test_score_records_criteria_and_salary_estimate(tmp_path, monkeypatch):
    setup_job(tmp_path, monkeypatch)
    _seed_j1(tmp_path)
    from app.db import connect, get_job
    assert main(["score", "j1", "match", "--change", "3", "--skills", "5",
                 "--seniority", "5", "--salary", "4",
                 "--salary-estimate", "$170k-$185k base (est.)",
                 "AI", "eval", "lead"]) == 0
    conn = connect(str(tmp_path / "app.db"))
    job = get_job(conn, "j1")
    conn.close()
    assert job["criteria_scores"] == {"change": 3, "skills": 5, "seniority": 5, "salary": 4}
    assert job["salary_estimate"] == "$170k-$185k base (est.)"
    assert job["score_rationale"] == "AI eval lead"
    assert job["scored_at"]


def test_score_rejects_out_of_range_criterion(tmp_path, monkeypatch):
    setup_job(tmp_path, monkeypatch)
    _seed_j1(tmp_path)
    with pytest.raises(SystemExit):
        main(["score", "j1", "match", "--skills", "6", "reason"])


def test_add_duplicate_does_not_overwrite_posting(tmp_path, monkeypatch, capsys):
    setup_job(tmp_path, monkeypatch)
    url = "https://acme.example/jobs/1"
    assert main(["add", "Acme", "Engineer", url]) == 0
    posting = next((tmp_path / "jobs").glob("*/posting.md"))
    posting.write_text(posting.read_text() + "\nFull description pasted in.\n")
    assert main(["add", "Acme", "Engineer", url]) == 0
    assert "Full description pasted in." in posting.read_text()


def test_pending_unscored_lists_never_scored_jobs(tmp_path, monkeypatch, capsys):
    setup_job(tmp_path, monkeypatch)
    _seed_j1(tmp_path)
    assert main(["pending"]) == 0
    assert "j1" not in capsys.readouterr().out
    assert main(["pending", "--unscored"]) == 0
    assert "j1 Acme - Eng [unscored]" in capsys.readouterr().out
    main(["score", "j1", "match", "fits"])
    capsys.readouterr()
    main(["pending", "--unscored"])
    assert "j1" not in capsys.readouterr().out
