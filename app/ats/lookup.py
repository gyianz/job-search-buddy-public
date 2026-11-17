"""Look up a single job posting from its link, to pre-fill "Add job".

Supported job boards are read through their public job APIs. Other sites
get one fetch of the page, read from its schema.org JobPosting data (or,
failing that, its title). LinkedIn and SEEK are never fetched: their terms
forbid automated access, so the user pastes the description instead.
"""
import json
import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urlparse

import httpx

from app.ats.smartrecruiters import API as SR_API, _SECTIONS as SR_SECTIONS
from app.ats.text import html_to_text

USER_AGENT = "job-search-buddy (personal job tracker)"
MAX_PAGE_BYTES = 3_000_000

_NO_FETCH = {
    "linkedin.com": "LinkedIn",
    "seek.com": "SEEK",
    "seek.com.au": "SEEK",
    "seek.co.nz": "SEEK",
    "indeed.com": "Indeed",
}


class JobLookupError(Exception):
    """A user-facing reason the link couldn't be read."""


def _result(title, company, location, description, source):
    return {
        "title": (title or "").strip(),
        "company": (company or "").strip(),
        "location": (location or "").strip(),
        "description": (description or "").strip(),
        "source": source,
    }


def _pretty(token: str) -> str:
    """Board token to a readable company name, e.g. 'culture-amp' -> 'Culture Amp'."""
    return re.sub(r"[-_]+", " ", token).strip().title()


def _greenhouse(host, parts, query, client):
    job_id = (query.get("gh_jid") or [None])[0]
    if "jobs" in parts:
        i = parts.index("jobs")
        token = parts[i - 1] if i > 0 else None
        job_id = job_id or (parts[i + 1] if i + 1 < len(parts) else None)
    else:
        token = parts[0] if parts else None
    if not token or not job_id:
        raise JobLookupError("That Greenhouse link doesn't point at a single job.")
    resp = client.get(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}")
    resp.raise_for_status()
    job = resp.json()
    return _result(
        job.get("title"),
        job.get("company_name") or _pretty(token),
        (job.get("location") or {}).get("name"),
        html_to_text(job.get("content") or ""),
        "greenhouse",
    )


def _lever(host, parts, query, client):
    if len(parts) < 2:
        raise JobLookupError("That Lever link doesn't point at a single job.")
    company, posting_id = parts[0], parts[1]
    resp = client.get(f"https://api.lever.co/v0/postings/{company}/{posting_id}")
    resp.raise_for_status()
    job = resp.json()
    sections = [job.get("descriptionPlain") or ""]
    for item in job.get("lists") or []:
        body = html_to_text(item.get("content") or "")
        sections.append(f"## {item.get('text', '').strip()}\n\n{body}")
    if job.get("additionalPlain"):
        sections.append(job["additionalPlain"])
    return _result(
        job.get("text"),
        _pretty(company),
        (job.get("categories") or {}).get("location"),
        "\n\n".join(s.strip() for s in sections if s.strip()),
        "lever",
    )


def _ashby(host, parts, query, client):
    if len(parts) < 2:
        raise JobLookupError("That Ashby link doesn't point at a single job.")
    board, job_id = parts[0], parts[1]
    resp = client.get(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    resp.raise_for_status()
    for job in resp.json().get("jobs", []):
        if job.get("id") == job_id or job.get("jobUrl", "").rstrip("/").endswith(job_id):
            return _result(
                job.get("title"), _pretty(board), job.get("location"),
                job.get("descriptionPlain"), "ashby",
            )
    raise JobLookupError("Couldn't find that job on the company's Ashby board; it may have closed.")


def _smartrecruiters(host, parts, query, client):
    if len(parts) < 2:
        raise JobLookupError("That SmartRecruiters link doesn't point at a single job.")
    company = parts[0]
    posting_id = parts[1].split("-", 1)[0]
    resp = client.get(f"{SR_API}/{company}/postings/{posting_id}")
    resp.raise_for_status()
    job = resp.json()
    sections = (job.get("jobAd") or {}).get("sections") or {}
    texts = []
    for key in SR_SECTIONS:
        section = sections.get(key) or {}
        body = html_to_text(section.get("text") or "")
        if body:
            texts.append(f"## {section['title']}\n\n{body}" if section.get("title") else body)
    loc = job.get("location") or {}
    return _result(
        job.get("name"),
        (job.get("company") or {}).get("name") or _pretty(company),
        loc.get("fullLocation") or loc.get("city"),
        "\n\n".join(texts),
        "smartrecruiters",
    )


def _workable(host, parts, query, client):
    # apply.workable.com/<account>/j/<shortcode>
    if "j" not in parts or parts.index("j") == 0 or parts.index("j") + 1 >= len(parts):
        raise JobLookupError(
            "Workable short links don't say which company they belong to; "
            "open the job and use the link that includes the company name."
        )
    i = parts.index("j")
    account, shortcode = parts[i - 1], parts[i + 1]
    resp = client.get(
        f"https://apply.workable.com/api/v1/widget/accounts/{account}", params={"details": "true"}
    )
    resp.raise_for_status()
    data = resp.json()
    for job in data.get("jobs", []):
        if job.get("shortcode") == shortcode:
            location = ", ".join(p for p in (job.get("city"), job.get("state"), job.get("country")) if p)
            return _result(
                job.get("title"), data.get("name") or _pretty(account), location,
                html_to_text(job.get("description") or ""), "workable",
            )
    raise JobLookupError("Couldn't find that job on the company's Workable page; it may have closed.")


_BOARDS = [
    ("greenhouse.io", _greenhouse),
    ("lever.co", _lever),
    ("ashbyhq.com", _ashby),
    ("smartrecruiters.com", _smartrecruiters),
    ("workable.com", _workable),
]

_LD_JSON = re.compile(
    r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.S | re.I
)


def _iter_ld(node):
    if isinstance(node, list):
        for item in node:
            yield from _iter_ld(item)
    elif isinstance(node, dict):
        yield node
        yield from _iter_ld(node.get("@graph", []))


def _ld_location(job):
    locs = job.get("jobLocation") or []
    locs = locs if isinstance(locs, list) else [locs]
    names = []
    for loc in locs:
        addr = (loc or {}).get("address") or {}
        if isinstance(addr, str):
            names.append(addr)
            continue
        parts = [addr.get("addressLocality"), addr.get("addressRegion"), addr.get("addressCountry")]
        parts = [p.get("name") if isinstance(p, dict) else p for p in parts]
        name = ", ".join(p for p in parts if p)
        if name:
            names.append(name)
    if job.get("jobLocationType") == "TELECOMMUTE":
        names.append("Remote")
    return "; ".join(dict.fromkeys(names))


def _meta(html, prop):
    m = re.search(
        rf'<meta[^>]+(?:property|name)=["\']{prop}["\'][^>]+content=["\']([^"\']*)', html, re.I
    )
    return unescape(m.group(1)).strip() if m else ""


def _generic(url, client):
    resp = client.get(url, headers={"User-Agent": USER_AGENT})
    resp.raise_for_status()
    if "html" not in resp.headers.get("content-type", "html"):
        raise JobLookupError("That link isn't a web page.")
    html = resp.text[:MAX_PAGE_BYTES]

    for block in _LD_JSON.findall(html):
        try:
            data = json.loads(unescape(block).strip())
        except ValueError:
            continue
        for node in _iter_ld(data):
            types = node.get("@type")
            types = types if isinstance(types, list) else [types]
            if "JobPosting" in types:
                org = node.get("hiringOrganization") or {}
                return _result(
                    node.get("title"),
                    org.get("name") if isinstance(org, dict) else org,
                    _ld_location(node),
                    html_to_text(node.get("description") or ""),
                    "manual",
                )

    title, company, description = _read_page(html)
    if not title:
        raise JobLookupError("Couldn't find any job details on that page; fill the form in by hand.")
    result = _result(title, company, "", description, "manual")
    if len(description) < 300:
        result["partial"] = True
    return result


class _ContentFinder(HTMLParser):
    """Find the page's main block of text, roughly as browser reader modes do.

    Each paragraph or list item credits its text to its parent element in
    full and to its grandparent by half; the highest-scoring element is
    taken to be the main content.
    """

    _SKIP = {"script", "style", "noscript", "template", "svg", "nav", "header", "footer", "form", "button", "select"}
    _BLOCKS = {"p", "li", "h1", "h2", "h3", "h4", "h5", "h6", "dd", "dt", "td", "blockquote", "pre"}
    _BREAK_AFTER = _BLOCKS | {"div", "section", "article", "main", "ul", "ol", "dl", "tr", "table", "br"}
    _VOID = {"br", "img", "hr", "input", "meta", "link", "area", "base", "col", "embed", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # open elements: [tag, node]
        self.nodes = []
        self.skip_depth = 0
        self.h1 = ""
        self._in_h1 = False

    def _new(self, tag, attrs, parent):
        node = {"tag": tag, "attrs": dict(attrs), "parent": parent, "parts": [], "score": 0.0, "own": []}
        self.nodes.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        if tag in self._VOID:
            if tag == "br":
                self._emit("\n")
            return
        if self.skip_depth or tag in self._SKIP:
            self.skip_depth += 1
            return
        parent = self.stack[-1] if self.stack else None
        node = self._new(tag, attrs, parent)
        if tag == "li":
            self._emit("\n- ")
        self.stack.append(node)
        if tag == "h1" and not self.h1:
            self._in_h1 = True

    def handle_endtag(self, tag):
        if self.skip_depth:
            self.skip_depth -= 1
            return
        # Close up to the matching open tag (HTML in the wild is not always tidy).
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i]["tag"] == tag:
                closing = self.stack[i:]
                del self.stack[i:]
                for node in reversed(closing):
                    self._close(node)
                break

    def _close(self, node):
        if node["tag"] == "h1" and self._in_h1:
            self.h1 = " ".join("".join(node["own"]).split())
            self._in_h1 = False
        if node["tag"] in self._BLOCKS:
            words = len("".join(node["own"]).split())
            if words and node["parent"]:
                node["parent"]["score"] += words
                if node["parent"]["parent"]:
                    node["parent"]["parent"]["score"] += words / 2
        if node["tag"] in self._BREAK_AFTER:
            self._emit("\n")

    def _emit(self, text):
        for node in self.stack:
            node["parts"].append(text)

    def handle_data(self, data):
        if self.skip_depth:
            return
        self._emit(data)
        if self.stack:
            for node in reversed(self.stack):
                node["own"].append(data)
                if node["tag"] in self._BLOCKS:
                    break

    @staticmethod
    def _length(node) -> int:
        return len("".join(node["parts"]).split())

    def main_text(self) -> str:
        best = max(self.nodes, key=lambda n: n["score"], default=None)
        if not best or best["score"] < 20:
            return ""
        # Widen to the enclosing block when it only adds a little (e.g. the
        # salary / location bullets sitting just above the paragraphs).
        while best["parent"] and best["parent"]["tag"] not in ("body", "html"):
            if self._length(best["parent"]) > self._length(best) * 1.5:
                break
            best = best["parent"]
        lines = [" ".join(line.split()) for line in "".join(best["parts"]).splitlines()]
        text = "\n".join(line for line in lines if line and line != "-")
        return re.sub(r"\n{3,}", "\n\n", text).strip()


def _read_page(html: str) -> tuple[str, str, str]:
    """(title, company, description) from an ordinary job page with no job data."""
    finder = _ContentFinder()
    try:
        finder.feed(html)
        finder.close()
    except Exception:  # Malformed HTML: keep whatever was parsed.
        pass
    m = re.search(r"<title[^>]*>(.*?)</title>", html, re.S | re.I)
    page_title = " ".join(unescape(m.group(1)).split()) if m else ""
    title = finder.h1 or _meta(html, "og:title") or page_title

    company = _meta(html, "og:site_name")
    if not company and finder.h1 and finder.h1 in page_title:
        # "ATO Careers - <job title>" -> "ATO"
        rest = page_title.replace(finder.h1, " ")
        rest = re.sub(r"^[\s|\-–—:]+|[\s|\-–—:]+$", "", rest)
        company = re.sub(r"\s+(careers?|jobs?)$", "", rest, flags=re.I).strip()

    description = finder.main_text() or _meta(html, "og:description")
    return title, company, description


def lookup_job(url: str, client: httpx.Client) -> dict:
    """Return {title, company, location, description, source} for a job link.

    Raises JobLookupError with a message to show the user if the link can't be
    read (unsupported site, closed job, network error).
    """
    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise JobLookupError("Enter a full link starting with https://")
    host = parsed.netloc.lower().split(":")[0]

    for domain, name in _NO_FETCH.items():
        if host == domain or host.endswith("." + domain):
            raise JobLookupError(
                f"{name} doesn't allow automated access, so copy the job description "
                "from the page and paste it in. The title and company still need typing."
            )

    parts = [p for p in parsed.path.split("/") if p]
    query = parse_qs(parsed.query)
    try:
        for domain, handler in _BOARDS:
            if host == domain or host.endswith("." + domain):
                return handler(host, parts, query, client)
        return _generic(url, client)
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 404:
            raise JobLookupError("That job wasn't found; it may have closed.") from exc
        raise JobLookupError(
            f"That site didn't return the page (error {exc.response.status_code}); "
            "it may block automated requests. Fill the details in by hand."
        ) from exc
    except httpx.HTTPError as exc:
        raise JobLookupError(f"Couldn't reach the site ({type(exc).__name__}).") from exc
