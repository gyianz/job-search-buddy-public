from pathlib import Path

import httpx

from app.ats.ashby import fetch_ashby
from app.ats.fetch import fetch_all
from app.ats.smartrecruiters import fetch_smartrecruiters
from app.ats.workable import fetch_workable
from app.db import connect, init_db, list_jobs


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetch_ashby_parses_jobs_and_skips_unlisted():
    def handler(request):
        assert request.url.path == "/posting-api/job-board/acme"
        return httpx.Response(200, json={"jobs": [
            {"title": "ML Engineer", "jobUrl": "https://jobs.ashbyhq.com/acme/1",
             "location": "Sydney", "secondaryLocations": [{"location": "Remote - APAC"}],
             "descriptionPlain": "Train models.", "isListed": True},
            {"title": "Hidden", "jobUrl": "https://jobs.ashbyhq.com/acme/2",
             "location": "Sydney", "isListed": False},
        ]})

    jobs = fetch_ashby("acme", _client(handler))
    assert jobs == [{
        "title": "ML Engineer", "url": "https://jobs.ashbyhq.com/acme/1",
        "location": "Sydney, Remote - APAC", "description": "Train models.",
    }]


def test_fetch_workable_parses_jobs():
    def handler(request):
        assert request.url.path == "/api/v1/widget/accounts/acme"
        assert request.url.params.get("details") == "true"
        return httpx.Response(200, json={"jobs": [
            {"title": "QA Engineer", "url": "https://apply.workable.com/j/ABC",
             "city": "Melbourne", "state": "Victoria", "country": "Australia",
             "telecommuting": True, "description": "<p>Test <b>things</b>.</p>"},
        ]})

    [job] = fetch_workable("acme", _client(handler))
    assert job["location"] == "Remote - Melbourne, Victoria, Australia"
    assert job["url"] == "https://apply.workable.com/j/ABC"
    assert "Test" in job["description"] and "<p>" not in job["description"]


def test_fetch_smartrecruiters_paginates():
    def handler(request):
        offset = int(request.url.params["offset"])
        page = [{"id": str(offset + i), "name": f"Job {offset + i} ",
                 "location": {"fullLocation": "Adelaide, SA, Australia"}} for i in range(2)]
        return httpx.Response(200, json={"totalFound": 3, "content": page if offset == 0 else page[:1]})

    jobs = fetch_smartrecruiters("Acme", _client(handler))
    assert [j["title"] for j in jobs] == ["Job 0", "Job 1", "Job 2"]
    assert jobs[0]["url"] == "https://jobs.smartrecruiters.com/Acme/0"
    assert jobs[0]["location"] == "Adelaide, SA, Australia"


def test_smartrecruiters_descriptions_only_loaded_for_new_matching_jobs(tmp_path, monkeypatch):
    detail_calls = []

    def handler(request):
        path = request.url.path
        if path.endswith("/postings"):
            return httpx.Response(200, json={"totalFound": 2, "content": [
                {"id": "1", "name": "Data Engineer", "location": {"city": "Sydney"}},
                {"id": "2", "name": "Barista", "location": {"city": "Sydney"}},
            ]})
        detail_calls.append(path)
        return httpx.Response(200, json={"jobAd": {"sections": {
            "jobDescription": {"title": "Job Description", "text": "<p>Build pipelines.</p>"},
        }}})

    client = _client(handler)
    conn = connect(":memory:"); init_db(conn)
    monkeypatch.chdir(tmp_path)
    seed = [{"name": "Acme", "platform": "smartrecruiters", "token": "Acme",
             "title_keywords": ["engineer"]}]

    assert fetch_all(conn, seed, client=client)["inserted"] == 1
    assert detail_calls == ["/v1/companies/Acme/postings/1"]
    text = Path(list_jobs(conn)[0]["posting_path"]).read_text()
    assert "## Job Description" in text and "Build pipelines." in text

    # Second run: the job is already known, so no detail request is made.
    assert fetch_all(conn, seed, client=client)["inserted"] == 0
    assert len(detail_calls) == 1
