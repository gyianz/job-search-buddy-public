import httpx


def fetch_ashby(board: str, client: httpx.Client) -> list[dict]:
    """Fetch open jobs from an Ashby job board (jobs.ashbyhq.com/<board>).

    Returns a list of
    {"title": str, "url": str, "location": str | None, "description": str}.
    """
    response = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    response.raise_for_status()
    data = response.json()

    jobs = []
    for job in data.get("jobs", []):
        if job.get("isListed") is False:
            continue
        locations = [job.get("location")] + [
            loc.get("location") for loc in job.get("secondaryLocations") or []
        ]
        location = ", ".join(loc for loc in locations if loc) or None
        jobs.append(
            {
                "title": job["title"],
                "url": job["jobUrl"],
                "location": location,
                "description": job.get("descriptionPlain") or "",
            }
        )
    return jobs
