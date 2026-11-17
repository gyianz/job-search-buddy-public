from pathlib import Path

import httpx, pytest
from app.db import connect, init_db, list_jobs
from app.ats.fetch import fetch_all

class FakeTransport(httpx.MockTransport):
    pass

def test_fetch_all_inserts_and_dedups(tmp_path, monkeypatch):
    def handler(request):
        if "greenhouse" in str(request.url):
            return httpx.Response(200, json={"jobs": [
                {"title": "Backend Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "location": {"name": "Remote"}}
            ]})
        return httpx.Response(200, json=[
            {"text": "Platform Engineer", "hostedUrl": "https://jobs.lever.co/beta/2", "categories": {"location": "NYC"}}
        ])
    client = httpx.Client(transport=httpx.MockTransport(handler))
    conn = connect(":memory:"); init_db(conn)
    monkeypatch.chdir(tmp_path)
    seed = [{"name": "Acme", "platform": "greenhouse", "token": "acme"},
            {"name": "Beta", "platform": "lever", "token": "beta"}]
    result = fetch_all(conn, seed, client=client)
    assert result["inserted"] == 2
    assert result["errors"] == []
    assert len(list_jobs(conn)) == 2
    # second run with same seed must not duplicate
    result2 = fetch_all(conn, seed, client=client)
    assert result2["inserted"] == 0
    assert len(list_jobs(conn)) == 2

def test_fetch_all_continues_after_one_platform_errors(tmp_path, monkeypatch):
    def handler(request):
        if "greenhouse" in str(request.url):
            raise httpx.ConnectError("boom")
        return httpx.Response(200, json=[
            {"text": "Platform Engineer", "hostedUrl": "https://jobs.lever.co/beta/3", "categories": {"location": "NYC"}}
        ])
    client = httpx.Client(transport=httpx.MockTransport(handler))
    conn = connect(":memory:"); init_db(conn)
    monkeypatch.chdir(tmp_path)
    seed = [{"name": "Acme", "platform": "greenhouse", "token": "acme"},
            {"name": "Beta", "platform": "lever", "token": "beta"}]
    result = fetch_all(conn, seed, client=client)
    assert result["inserted"] == 1
    assert len(result["errors"]) == 1

def test_fetch_all_skips_unknown_platform(tmp_path, monkeypatch):
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=[])))
    conn = connect(":memory:"); init_db(conn)
    monkeypatch.chdir(tmp_path)
    result = fetch_all(conn, [{"name": "X", "platform": "workday", "token": "x"}], client=client)
    assert result["inserted"] == 0
    assert len(result["errors"]) == 1


def test_fetch_all_survives_malformed_seed_entry(tmp_path, monkeypatch):
    # Entry missing "platform"/"token" keys must not abort the whole run,
    # and the error message must not itself crash on the missing "name".
    def handler(request):
        return httpx.Response(200, json=[
            {"text": "Platform Engineer", "hostedUrl": "https://jobs.lever.co/beta/9", "categories": {"location": "NYC"}}
        ])
    client = httpx.Client(transport=httpx.MockTransport(handler))
    conn = connect(":memory:"); init_db(conn)
    monkeypatch.chdir(tmp_path)
    seed = [{"broken": "entry"}, {"name": "Beta", "platform": "lever", "token": "beta"}]
    result = fetch_all(conn, seed, client=client)
    assert result["inserted"] == 1
    assert len(result["errors"]) == 1
    assert "broken" in result["errors"][0] or "entry" in result["errors"][0]
    assert len(list_jobs(conn)) == 1


def test_fetch_all_includes_description_in_posting_md(tmp_path, monkeypatch):
    def handler(request):
        if "greenhouse" in str(request.url):
            assert request.url.params.get("content") == "true"
            return httpx.Response(200, json={"jobs": [
                {"title": "Backend Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
                 "location": {"name": "Remote"},
                 "content": "&lt;p&gt;Build &lt;b&gt;cool&lt;/b&gt; stuff.&lt;/p&gt;&lt;p&gt;Requires Python.&lt;/p&gt;"}
            ]})
        return httpx.Response(200, json=[
            {"text": "Platform Engineer", "hostedUrl": "https://jobs.lever.co/beta/4",
             "categories": {"location": "NYC"}, "descriptionPlain": "Own the platform."}
        ])
    client = httpx.Client(transport=httpx.MockTransport(handler))
    conn = connect(":memory:"); init_db(conn)
    monkeypatch.chdir(tmp_path)
    seed = [{"name": "Acme", "platform": "greenhouse", "token": "acme"},
            {"name": "Beta", "platform": "lever", "token": "beta"}]
    fetch_all(conn, seed, client=client)

    jobs = {j["company"]: j for j in list_jobs(conn)}
    gh_text = Path(jobs["Acme"]["posting_path"]).read_text()
    assert "Build" in gh_text and "cool" in gh_text and "Requires Python" in gh_text
    assert "<p>" not in gh_text and "<b>" not in gh_text

    lever_text = Path(jobs["Beta"]["posting_path"]).read_text()
    assert "Own the platform." in lever_text


def test_fetch_all_applies_title_and_location_filters(tmp_path, monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"jobs": [
            {"title": "Senior Software Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
             "location": {"name": "Remote - Australia"}},
            {"title": "Support Specialist", "absolute_url": "https://boards.greenhouse.io/acme/jobs/2",
             "location": {"name": "Remote - Australia"}},
            {"title": "Senior Software Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/3",
             "location": {"name": "United States"}},
        ]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    conn = connect(":memory:"); init_db(conn)
    monkeypatch.chdir(tmp_path)
    seed = [{"name": "Acme", "platform": "greenhouse", "token": "acme",
             "title_keywords": ["engineer"], "location_keywords": ["australia", "remote"]}]
    result = fetch_all(conn, seed, client=client)
    assert result["inserted"] == 1
    jobs = list_jobs(conn)
    assert jobs[0]["title"] == "Senior Software Engineer"
    assert jobs[0]["location"] == "Remote - Australia"


def test_fetch_all_no_filters_keeps_everything(tmp_path, monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"jobs": [
            {"title": "Support Specialist", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1",
             "location": {"name": "Canada"}},
        ]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    conn = connect(":memory:"); init_db(conn)
    monkeypatch.chdir(tmp_path)
    seed = [{"name": "Acme", "platform": "greenhouse", "token": "acme"}]
    result = fetch_all(conn, seed, client=client)
    assert result["inserted"] == 1


def test_fetch_all_does_not_overwrite_posting_on_duplicate(tmp_path, monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"jobs": [
            {"title": "Backend Engineer", "absolute_url": "https://boards.greenhouse.io/acme/jobs/1", "location": {"name": "Remote"}}
        ]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    conn = connect(":memory:"); init_db(conn)
    monkeypatch.chdir(tmp_path)
    seed = [{"name": "Acme", "platform": "greenhouse", "token": "acme"}]

    result = fetch_all(conn, seed, client=client)
    assert result["inserted"] == 1
    job = list_jobs(conn)[0]
    posting_path = Path(job["posting_path"])
    assert posting_path.exists()

    # Simulate a manual edit to the posting file.
    posting_path.write_text("hand-edited content")

    result2 = fetch_all(conn, seed, client=client)
    assert result2["inserted"] == 0
    assert posting_path.read_text() == "hand-edited content"


def test_fetch_all_skips_deleted_jobs(tmp_path, monkeypatch):
    from app.storage import job_id_for_url, move_to_trash
    url = "https://boards.greenhouse.io/acme/jobs/1"
    def handler(request):
        return httpx.Response(200, json={"jobs": [
            {"title": "Backend Engineer", "absolute_url": url, "location": {"name": "Remote"}}
        ]})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    conn = connect(":memory:"); init_db(conn)
    monkeypatch.chdir(tmp_path)
    move_to_trash(job_id_for_url(url))
    result = fetch_all(conn, [{"name": "Acme", "platform": "greenhouse", "token": "acme"}], client=client)
    assert result["inserted"] == 0
    assert list_jobs(conn) == []
