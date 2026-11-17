import httpx

from app.ats.text import html_to_text

API = "https://api.smartrecruiters.com/v1/companies"
PAGE_SIZE = 100
_SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


def _description_loader(company: str, posting_id: str, client: httpx.Client):
    """The list endpoint has no job text, so fetch it only when it's needed."""

    def load() -> str:
        response = client.get(f"{API}/{company}/postings/{posting_id}")
        response.raise_for_status()
        sections = (response.json().get("jobAd") or {}).get("sections") or {}
        texts = []
        for key in _SECTIONS:
            section = sections.get(key) or {}
            body = html_to_text(section.get("text") or "")
            if body:
                title = section.get("title")
                texts.append(f"## {title}\n\n{body}" if title else body)
        return "\n\n".join(texts)

    return load


def fetch_smartrecruiters(company: str, client: httpx.Client) -> list[dict]:
    """Fetch open postings from a SmartRecruiters company (jobs.smartrecruiters.com/<company>).

    Returns a list of
    {"title": str, "url": str, "location": str | None, "load_description": callable}.
    The description is loaded lazily (one request per posting), so fetch_all
    only pays for it on postings that pass the filters and are new.
    """
    jobs = []
    offset = 0
    while True:
        response = client.get(
            f"{API}/{company}/postings", params={"limit": PAGE_SIZE, "offset": offset}
        )
        response.raise_for_status()
        data = response.json()
        content = data.get("content") or []

        for posting in content:
            loc = posting.get("location") or {}
            location = loc.get("fullLocation") or ", ".join(
                p for p in (loc.get("city"), loc.get("region"), loc.get("country")) if p
            )
            if loc.get("remote"):
                location = f"Remote - {location}" if location else "Remote"
            jobs.append(
                {
                    "title": posting["name"].strip(),
                    "url": f"https://jobs.smartrecruiters.com/{company}/{posting['id']}",
                    "location": location or None,
                    "load_description": _description_loader(company, posting["id"], client),
                }
            )

        offset += len(content)
        if not content or offset >= data.get("totalFound", 0):
            break
    return jobs
