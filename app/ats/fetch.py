import json
import sqlite3
from datetime import datetime, timezone

import httpx

from app.db import get_job, insert_job
from app.storage import is_trashed, job_dir, job_id_for_url, write_posting
from app.ats.ashby import fetch_ashby
from app.ats.greenhouse import fetch_greenhouse
from app.ats.lever import fetch_lever
from app.ats.smartrecruiters import fetch_smartrecruiters
from app.ats.workable import fetch_workable

FETCHERS = {
    "greenhouse": fetch_greenhouse,
    "lever": fetch_lever,
    "ashby": fetch_ashby,
    "smartrecruiters": fetch_smartrecruiters,
    "workable": fetch_workable,
}


def load_seed(path: str = "seed_companies.json") -> list[dict]:
    """Load the seed company list from a JSON file."""
    with open(path) as f:
        return json.load(f)


def _matches_filters(title: str, location: str | None, entry: dict) -> bool:
    """A posting matches if it passes both the title and location filters.

    Each filter is an optional list of keywords on the seed entry
    ("title_keywords", "location_keywords"); a posting matches a filter if
    ANY keyword is a case-insensitive substring of the field, or if the
    filter is absent/empty (no restriction on that field).
    """
    title_keywords = entry.get("title_keywords") or []
    if title_keywords:
        title_lower = title.lower()
        if not any(kw.lower() in title_lower for kw in title_keywords):
            return False

    location_keywords = entry.get("location_keywords") or []
    if location_keywords:
        location_lower = (location or "").lower()
        if not any(kw.lower() in location_lower for kw in location_keywords):
            return False

    return True


def fetch_all(
    conn: sqlite3.Connection,
    seed: list[dict],
    client: httpx.Client | None = None,
) -> dict:
    """Fetch postings for every seed entry and insert new jobs into the DB.

    Returns {"inserted": int, "errors": list[str]}.
    A single entry's failure (unknown platform, fetch error, etc.) is
    caught and recorded without stopping the rest of the run.
    """
    owns_client = client is None
    if client is None:
        client = httpx.Client()

    inserted = 0
    errors = []

    try:
        for entry in seed:
            try:
                name = entry["name"]
                platform = entry["platform"]
                token = entry["token"]

                fetcher = FETCHERS.get(platform)
                if fetcher is None:
                    raise ValueError(f"unknown platform '{platform}'")

                postings = fetcher(token, client)
                for posting in postings:
                    title = posting["title"]
                    url = posting["url"]
                    location = posting["location"]
                    if not _matches_filters(title, location, entry):
                        continue

                    job_id = job_id_for_url(url)
                    if get_job(conn, job_id) is not None or is_trashed(job_id):
                        continue

                    description = posting.get("description")
                    if description is None and "load_description" in posting:
                        description = posting["load_description"]()
                    description = description or ""
                    job_path = job_dir(job_id) / "posting.md"

                    job = {
                        "id": job_id,
                        "source": platform,
                        "company": name,
                        "title": title,
                        "location": location,
                        "url": url,
                        "posting_path": str(job_path),
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    }
                    if insert_job(conn, job):
                        inserted += 1
                        markdown = (
                            f"# {title}\n\n"
                            f"**Company:** {name}\n"
                            f"**Location:** {location}\n"
                            f"**Source URL:** {url}\n\n"
                            f"{description}\n"
                        )
                        write_posting(job_id, markdown)
            except Exception as exc:
                errors.append(f"{entry.get('name', entry)}: {exc}")
    finally:
        if owns_client:
            client.close()

    return {"inserted": inserted, "errors": errors}
