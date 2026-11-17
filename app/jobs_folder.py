"""Load listings saved under jobs/<id>/posting.md into the database.

The jobs/ folder is version-controlled, while the database is not, so a
fresh checkout (or a posting added by hand, e.g. from LinkedIn or SEEK)
would otherwise never show up on the board.
"""
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from app.db import insert_job, set_tailored_paths
from app.storage import job_id_for_url, write_posting

_FIELD = re.compile(r"^\*\*(?P<key>[^*]+?):\*\*\s*(?P<value>.*)$")

# Host substring -> source label shown on the board.
_SOURCES = [
    ("greenhouse", "greenhouse"),
    ("lever.co", "lever"),
    ("ashbyhq", "ashby"),
    ("smartrecruiters", "smartrecruiters"),
    ("workable", "workable"),
    ("linkedin", "linkedin"),
    ("seek.com", "seek"),
]


def parse_posting(text: str) -> dict:
    """Pull the title and the **Key:** header fields out of a posting.md."""
    fields: dict[str, str] = {}
    title = None
    for line in text.splitlines():
        line = line.strip()
        if title is None and line.startswith("# "):
            title = line[2:].strip()
            continue
        match = _FIELD.match(line)
        if match:
            fields.setdefault(match["key"].strip().lower(), match["value"].strip())
    return {
        "title": title,
        "company": fields.get("company"),
        "location": fields.get("location"),
        "url": fields.get("source url"),
    }


def _source_for(url: str) -> str:
    host = urlparse(url).netloc.lower()
    for needle, label in _SOURCES:
        if needle in host:
            return label
    return "manual"


def _first_existing(folder: Path, names: tuple[str, ...]) -> str | None:
    for name in names:
        if (folder / name).exists():
            return str(folder / name)
    return None


def sync_jobs_folder(conn: sqlite3.Connection, base: Path = Path("jobs")) -> int:
    """Insert any job folder that isn't in the database yet.

    Returns the number of jobs added. Jobs already in the database are left
    alone, so statuses and scores recorded there are never overwritten.
    """
    if not base.is_dir():
        return 0

    known = {row[0] for row in conn.execute("SELECT id FROM jobs")}
    added = 0
    for posting_path in sorted(base.glob("*/posting.md")):
        folder = posting_path.parent
        job_id = folder.name
        if job_id in known:
            continue

        info = parse_posting(posting_path.read_text(errors="replace"))
        url = info["url"] or f"local:{job_id}"
        mtime = datetime.fromtimestamp(posting_path.stat().st_mtime, timezone.utc)
        job = {
            "id": job_id,
            "source": _source_for(url),
            "company": info["company"] or "Unknown company",
            "title": info["title"] or job_id,
            "location": info["location"],
            "url": url,
            "posting_path": str(posting_path),
            "fetched_at": mtime.isoformat(),
        }
        if not insert_job(conn, job):
            continue  # Same URL already tracked under another id.
        added += 1

        resume = _first_existing(folder, ("tailored_resume.md", "tailored_resume.pdf"))
        cover = _first_existing(folder, ("cover_letter.md", "cover_letter.pdf"))
        if resume or cover:
            set_tailored_paths(conn, job_id, resume, cover)
    return added


def add_job(
    conn: sqlite3.Connection,
    *,
    company: str,
    title: str,
    url: str | None = None,
    location: str | None = None,
    description: str = "",
    base: Path = Path("jobs"),
) -> tuple[str, bool]:
    """Save a hand-added posting to jobs/<id>/posting.md and the database.

    Returns (job_id, created). If the URL is already tracked, nothing is
    written and the existing job's id is returned with created=False, so an
    existing posting (and any edits to it) is never overwritten.
    """
    company, title = company.strip(), title.strip()
    if not company or not title:
        raise ValueError("company and title are required")
    url = (url or "").strip() or None
    location = (location or "").strip() or None

    if url:
        row = conn.execute("SELECT id FROM jobs WHERE url = ?", (url,)).fetchone()
        if row:
            return row[0], False
        job_id = job_id_for_url(url)
    else:
        job_id = uuid.uuid4().hex[:12]
        url = f"local:{job_id}"

    if (base / job_id / "posting.md").exists():
        # Saved on disk but not loaded yet: load it rather than overwrite it.
        sync_jobs_folder(conn, base)
        return job_id, False

    markdown = (
        f"# {title}\n\n"
        f"**Company:** {company}\n"
        f"**Location:** {location or ''}\n"
        f"**Source URL:** {url}\n"
    )
    if description.strip():
        markdown += f"\n{description.strip()}\n"
    posting_path = write_posting(job_id, markdown, base)
    insert_job(
        conn,
        {
            "id": job_id,
            "source": _source_for(url),
            "company": company,
            "title": title,
            "location": location,
            "url": url,
            "posting_path": str(posting_path),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return job_id, True
