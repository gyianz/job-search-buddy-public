from app.db import connect, get_job, init_db, update_status
from app.jobs_folder import parse_posting, sync_jobs_folder


def _write(base, job_id, text, extra=()):
    folder = base / job_id
    folder.mkdir(parents=True)
    (folder / "posting.md").write_text(text)
    for name in extra:
        (folder / name).write_text("x")


POSTING = """# AI Delivery Lead

**Company:** RAA
**Location:** Adelaide, SA
**Source URL:** https://www.linkedin.com/jobs/view/123/

Body text.
"""


def test_parse_posting_reads_header():
    assert parse_posting(POSTING) == {
        "title": "AI Delivery Lead", "company": "RAA",
        "location": "Adelaide, SA", "url": "https://www.linkedin.com/jobs/view/123/",
    }


def test_sync_adds_folder_jobs_with_tailored_docs(tmp_path):
    base = tmp_path / "jobs"
    _write(base, "abc123", POSTING, extra=("tailored_resume.md", "cover_letter.md"))
    _write(base, "noheader", "just some text")
    conn = connect(":memory:"); init_db(conn)

    assert sync_jobs_folder(conn, base) == 2

    job = get_job(conn, "abc123")
    assert job["company"] == "RAA"
    assert job["source"] == "linkedin"
    assert job["status"] == "new"
    assert job["tailored_resume_path"].endswith("abc123/tailored_resume.md")
    assert job["tailored_cover_letter_path"].endswith("abc123/cover_letter.md")

    fallback = get_job(conn, "noheader")
    assert fallback["title"] == "noheader"
    assert fallback["url"] == "local:noheader"


def test_sync_is_idempotent_and_keeps_db_state(tmp_path):
    base = tmp_path / "jobs"
    _write(base, "abc123", POSTING)
    conn = connect(":memory:"); init_db(conn)
    sync_jobs_folder(conn, base)
    update_status(conn, "abc123", "applied")

    assert sync_jobs_folder(conn, base) == 0
    assert get_job(conn, "abc123")["status"] == "applied"


def test_sync_skips_duplicate_url_under_another_id(tmp_path):
    base = tmp_path / "jobs"
    _write(base, "aaa", POSTING)
    _write(base, "bbb", POSTING)
    conn = connect(":memory:"); init_db(conn)
    assert sync_jobs_folder(conn, base) == 1


def test_sync_missing_folder_is_noop(tmp_path):
    conn = connect(":memory:"); init_db(conn)
    assert sync_jobs_folder(conn, tmp_path / "nope") == 0
