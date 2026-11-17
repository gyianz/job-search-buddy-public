import sqlite3
import pytest
from app.db import (
    connect,
    init_db,
    insert_job,
    list_jobs,
    get_job,
    update_status,
    set_needs_scoring,
    set_needs_tailoring,
    set_score,
    set_tailored_paths,
)


def make_job(url="https://x.example/job/1", **overrides):
    job = dict(
        id="abc123",
        source="greenhouse",
        company="Acme",
        title="Engineer",
        location="Remote",
        url=url,
        posting_path="jobs/abc123/posting.md",
        fetched_at="2026-11-03T00:00:00",
    )
    job.update(overrides)
    return job


def test_insert_and_dedup_by_url():
    conn = connect(":memory:")
    init_db(conn)
    assert insert_job(conn, make_job()) is True
    assert insert_job(conn, make_job(id="other")) is False  # same url
    assert len(list_jobs(conn)) == 1


def test_list_jobs_hides_passed_by_default():
    conn = connect(":memory:")
    init_db(conn)
    insert_job(conn, make_job())
    update_status(conn, "abc123", "passed")
    assert list_jobs(conn) == []
    assert len(list_jobs(conn, include_closed=True)) == 1


def test_update_status_rejects_unknown_value():
    conn = connect(":memory:")
    init_db(conn)
    insert_job(conn, make_job())
    with pytest.raises(ValueError):
        update_status(conn, "abc123", "ghosted")


def test_set_score_clears_needs_scoring():
    conn = connect(":memory:")
    init_db(conn)
    insert_job(conn, make_job())
    set_needs_scoring(conn, "abc123")
    set_score(conn, "abc123", "match", "Strong fit on backend experience.")
    job = get_job(conn, "abc123")
    assert job["needs_scoring"] == 0
    assert job["score_bucket"] == "match"


def test_update_status_rejects_missing_job_id():
    conn = connect(":memory:")
    init_db(conn)
    with pytest.raises(ValueError):
        update_status(conn, "does-not-exist", "applied")


def test_set_needs_scoring_rejects_missing_job_id():
    conn = connect(":memory:")
    init_db(conn)
    with pytest.raises(ValueError):
        set_needs_scoring(conn, "does-not-exist")


def test_set_needs_tailoring_rejects_missing_job_id():
    conn = connect(":memory:")
    init_db(conn)
    with pytest.raises(ValueError):
        set_needs_tailoring(conn, "does-not-exist")


def test_set_score_rejects_missing_job_id():
    conn = connect(":memory:")
    init_db(conn)
    with pytest.raises(ValueError):
        set_score(conn, "does-not-exist", "match", "reason")


def test_set_tailored_paths_rejects_missing_job_id():
    conn = connect(":memory:")
    init_db(conn)
    with pytest.raises(ValueError):
        set_tailored_paths(conn, "does-not-exist", "resume.md", "cover.md")


def test_init_db_adds_score_columns_to_old_database(tmp_path):
    import sqlite3
    from app.db import connect, init_db
    path = str(tmp_path / "old.db")
    raw = sqlite3.connect(path)
    raw.execute("""CREATE TABLE jobs (id TEXT PRIMARY KEY, source TEXT NOT NULL, company TEXT NOT NULL,
        title TEXT NOT NULL, location TEXT, url TEXT NOT NULL UNIQUE, posting_path TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'new', score_bucket TEXT, score_rationale TEXT,
        needs_scoring INTEGER NOT NULL DEFAULT 0, needs_tailoring INTEGER NOT NULL DEFAULT 0,
        tailored_resume_path TEXT, tailored_cover_letter_path TEXT, fetched_at TEXT NOT NULL, scored_at TEXT)""")
    raw.execute("INSERT INTO jobs (id, source, company, title, url, posting_path, fetched_at) "
                "VALUES ('a', 'gh', 'Acme', 'Eng', 'https://x/a', 'p', '2026-01-01')")
    raw.commit(); raw.close()

    conn = connect(path)
    init_db(conn)
    init_db(conn)  # idempotent
    cols = {r[1] for r in conn.execute("PRAGMA table_info(jobs)")}
    assert {"change_score", "skills_score", "seniority_score", "salary_score", "salary_estimate"} <= cols
    assert conn.execute("SELECT company FROM jobs WHERE id='a'").fetchone()[0] == "Acme"
