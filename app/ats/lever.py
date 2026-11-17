import httpx


def fetch_lever(company: str, client: httpx.Client) -> list[dict]:
    """Fetch open postings from a Lever job board, including descriptions.

    Returns a list of
    {"title": str, "url": str, "location": str | None, "description": str}.
    """
    response = client.get(
        f"https://api.lever.co/v0/postings/{company}?mode=json"
    )
    response.raise_for_status()
    data = response.json()

    jobs = []
    for posting in data:
        categories = posting.get("categories") or {}
        jobs.append(
            {
                "title": posting["text"],
                "url": posting["hostedUrl"],
                "location": categories.get("location"),
                "description": posting.get("descriptionPlain") or "",
            }
        )
    return jobs
