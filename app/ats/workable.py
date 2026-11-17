import httpx

from app.ats.text import html_to_text


def _location(job: dict) -> str | None:
    parts = [job.get("city"), job.get("state"), job.get("country")]
    location = ", ".join(p for p in parts if p)
    if job.get("telecommuting"):
        location = f"Remote - {location}" if location else "Remote"
    return location or None


def fetch_workable(account: str, client: httpx.Client) -> list[dict]:
    """Fetch open jobs from a Workable account (apply.workable.com/<account>).

    Returns a list of
    {"title": str, "url": str, "location": str | None, "description": str}.
    """
    response = client.get(
        f"https://apply.workable.com/api/v1/widget/accounts/{account}",
        params={"details": "true"},
    )
    response.raise_for_status()
    data = response.json()

    return [
        {
            "title": job["title"],
            "url": job["url"],
            "location": _location(job),
            "description": html_to_text(job.get("description") or ""),
        }
        for job in data.get("jobs", [])
    ]
