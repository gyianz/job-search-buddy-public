import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def connect(db_path: str) -> sqlite3.Connection:
    """Open a connection to the SQLite database with row_factory set to Row."""
    if db_path != ":memory:":
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# The original four criteria had their own jobs columns. Criteria now come from
# profile/rubric.json and their scores live in the criteria_scores table; these
# columns are only read once, to migrate older databases.
_LEGACY_CRITERIA = ("change", "skills", "seniority", "salary")

_ADDED_COLUMNS = [(f"{c}_score", "INTEGER") for c in _LEGACY_CRITERIA] + [("salary_estimate", "TEXT")]


def init_db(conn: sqlite3.Connection) -> None:
    """Initialize the database schema with the jobs table."""
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS jobs (
          id TEXT PRIMARY KEY,
          source TEXT NOT NULL,
          company TEXT NOT NULL,
          title TEXT NOT NULL,
          location TEXT,
          url TEXT NOT NULL UNIQUE,
          posting_path TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'new',
          score_bucket TEXT,
          score_rationale TEXT,
          needs_scoring INTEGER NOT NULL DEFAULT 0,
          needs_tailoring INTEGER NOT NULL DEFAULT 0,
          tailored_resume_path TEXT,
          tailored_cover_letter_path TEXT,
          fetched_at TEXT NOT NULL,
          scored_at TEXT
        )
        """
    )
    # Columns added after the first release; add them to older databases.
    existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
    for column, sql_type in _ADDED_COLUMNS:
        if column not in existing:
            conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {sql_type}")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS criteria_scores (
          job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
          criterion TEXT NOT NULL,
          score INTEGER NOT NULL,
          PRIMARY KEY (job_id, criterion)
        )
        """
    )
    # Move scores recorded in the legacy columns into criteria_scores.
    for c in _LEGACY_CRITERIA:
        conn.execute(
            f"INSERT OR IGNORE INTO criteria_scores (job_id, criterion, score) "
            f"SELECT id, ?, {c}_score FROM jobs WHERE {c}_score IS NOT NULL",
            (c,),
        )
        conn.execute(f"UPDATE jobs SET {c}_score = NULL WHERE {c}_score IS NOT NULL")
    conn.commit()


def _attach_scores(conn: sqlite3.Connection, jobs: list[dict]) -> list[dict]:
    """Add a criteria_scores dict ({criterion: 1-5}) to each job."""
    by_id = {job["id"]: job for job in jobs}
    for job in jobs:
        job["criteria_scores"] = {}
        for c in _LEGACY_CRITERIA:
            job.pop(f"{c}_score", None)
    for row in conn.execute("SELECT job_id, criterion, score FROM criteria_scores"):
        if row[0] in by_id:
            by_id[row[0]]["criteria_scores"][row[1]] = row[2]
    return jobs


def insert_job(conn: sqlite3.Connection, job: dict) -> bool:
    """
    Insert a job into the database.
    Returns True if inserted, False if a job with the same URL already exists.
    """
    try:
        conn.execute(
            """
            INSERT INTO jobs (
                id, source, company, title, location, url, posting_path, fetched_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["id"],
                job["source"],
                job["company"],
                job["title"],
                job["location"],
                job["url"],
                job["posting_path"],
                job["fetched_at"],
            ),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        # URL already exists, do not insert
        return False


def list_jobs(conn: sqlite3.Connection, include_closed: bool = False) -> list[dict]:
    """
    List all jobs, ordered by fetched_at descending (newest first).
    By default, excludes jobs with status='passed' unless include_closed=True.
    """
    if include_closed:
        query = "SELECT * FROM jobs ORDER BY fetched_at DESC"
        rows = conn.execute(query).fetchall()
    else:
        query = "SELECT * FROM jobs WHERE status != 'passed' ORDER BY fetched_at DESC"
        rows = conn.execute(query).fetchall()

    return _attach_scores(conn, [dict(row) for row in rows])


def get_job(conn: sqlite3.Connection, job_id: str) -> dict | None:
    """Get a single job by ID, returns None if not found."""
    row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if row is None:
        return None
    return _attach_scores(conn, [dict(row)])[0]


def update_status(conn: sqlite3.Connection, job_id: str, status: str) -> None:
    """
    Update the status of a job.
    Raises ValueError if status is not in the allowed set.
    """
    allowed_statuses = {"new", "interested", "applied", "interviewing", "rejected", "not_interested", "passed"}
    if status not in allowed_statuses:
        raise ValueError(f"Status must be one of {allowed_statuses}, got '{status}'")

    cursor = conn.execute("UPDATE jobs SET status = ? WHERE id = ?", (status, job_id))
    conn.commit()
    if cursor.rowcount == 0:
        raise ValueError(f"no job with id {job_id!r}")


def set_needs_scoring(conn: sqlite3.Connection, job_id: str) -> None:
    """Mark a job as needing scoring."""
    cursor = conn.execute("UPDATE jobs SET needs_scoring = 1 WHERE id = ?", (job_id,))
    conn.commit()
    if cursor.rowcount == 0:
        raise ValueError(f"no job with id {job_id!r}")


def set_needs_tailoring(conn: sqlite3.Connection, job_id: str) -> None:
    """Mark a job as needing tailoring."""
    cursor = conn.execute("UPDATE jobs SET needs_tailoring = 1 WHERE id = ?", (job_id,))
    conn.commit()
    if cursor.rowcount == 0:
        raise ValueError(f"no job with id {job_id!r}")


def set_score(
    conn: sqlite3.Connection,
    job_id: str,
    bucket: str,
    rationale: str,
    criteria: dict[str, int] | None = None,
    salary_estimate: str | None = None,
) -> None:
    """
    Set the score bucket, rationale and (optionally) criteria scores for a job.
    criteria maps criterion keys (see profile/rubric.json) to 1-5; any score
    not given is cleared.
    Also clears the needs_scoring flag and stamps scored_at.
    """
    criteria = criteria or {}
    for name, value in criteria.items():
        if not 1 <= value <= 5:
            raise ValueError(f"{name} score must be 1-5, got {value}")
    cursor = conn.execute(
        "UPDATE jobs SET score_bucket = ?, score_rationale = ?, "
        "salary_estimate = ?, needs_scoring = 0, scored_at = ? WHERE id = ?",
        (bucket, rationale, salary_estimate, datetime.now(timezone.utc).isoformat(), job_id),
    )
    if cursor.rowcount == 0:
        conn.rollback()
        raise ValueError(f"no job with id {job_id!r}")
    conn.execute("DELETE FROM criteria_scores WHERE job_id = ?", (job_id,))
    conn.executemany(
        "INSERT INTO criteria_scores (job_id, criterion, score) VALUES (?, ?, ?)",
        [(job_id, name, value) for name, value in criteria.items()],
    )
    conn.commit()


def set_tailored_paths(
    conn: sqlite3.Connection, job_id: str, resume_path: str, cover_letter_path: str
) -> None:
    """
    Set the tailored resume and cover letter paths for a job.
    Also clears the needs_tailoring flag.
    """
    cursor = conn.execute(
        "UPDATE jobs SET tailored_resume_path = ?, tailored_cover_letter_path = ?, needs_tailoring = 0 WHERE id = ?",
        (resume_path, cover_letter_path, job_id),
    )
    conn.commit()
    if cursor.rowcount == 0:
        raise ValueError(f"no job with id {job_id!r}")


def delete_job(conn: sqlite3.Connection, job_id: str) -> None:
    """Remove a job row. Raises ValueError if it doesn't exist."""
    conn.execute("DELETE FROM criteria_scores WHERE job_id = ?", (job_id,))
    cursor = conn.execute("DELETE FROM jobs WHERE id = ?", (job_id,))
    conn.commit()
    if cursor.rowcount == 0:
        raise ValueError(f"no job with id {job_id!r}")
