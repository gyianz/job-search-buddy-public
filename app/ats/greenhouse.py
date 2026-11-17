import httpx

from app.ats.text import html_to_text


def fetch_greenhouse(token: str, client: httpx.Client) -> list[dict]:
    """Fetch open jobs from a Greenhouse job board, including descriptions.

    Returns a list of
    {"title": str, "url": str, "location": str | None, "description": str}.
    """
    response = client.get(
        f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
        params={"content": "true"},
    )
    response.raise_for_status()
    data = response.json()

    jobs = []
    for job in data.get("jobs", []):
        location = job.get("location")
        jobs.append(
            {
                "title": job["title"],
                "url": job["absolute_url"],
                "location": location.get("name") if location else None,
                "description": html_to_text(job.get("content") or ""),
            }
        )
    return jobs
