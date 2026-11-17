import json

import httpx
import pytest

from app.ats.lookup import JobLookupError, lookup_job


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_greenhouse_link():
    def handler(request):
        assert request.url.path == "/v1/boards/acme/jobs/123"
        return httpx.Response(200, json={
            "title": "QA Lead", "company_name": "Acme Corp", "location": {"name": "Sydney"},
            "content": "&lt;p&gt;Lead &lt;b&gt;quality&lt;/b&gt;.&lt;/p&gt;",
        })
    job = lookup_job("https://job-boards.greenhouse.io/acme/jobs/123?utm=x", _client(handler))
    assert job == {"title": "QA Lead", "company": "Acme Corp", "location": "Sydney",
                   "description": "Lead\nquality\n.", "source": "greenhouse"}


def test_greenhouse_embed_link_with_gh_jid():
    def handler(request):
        assert request.url.path == "/v1/boards/figma/jobs/777"
        return httpx.Response(200, json={"title": "T", "company_name": "Figma", "location": None})
    assert lookup_job("https://boards.greenhouse.io/figma/jobs/777?gh_jid=777", _client(handler))["company"] == "Figma"


def test_lever_link_includes_requirement_lists():
    def handler(request):
        assert request.url.path == "/v0/postings/culture-amp/abc-123"
        return httpx.Response(200, json={
            "text": "Engineer", "categories": {"location": "Melbourne"},
            "descriptionPlain": "Intro.",
            "lists": [{"text": "Requirements", "content": "<li>Python</li><li>Testing</li>"}],
            "additionalPlain": "Benefits.",
        })
    job = lookup_job("https://jobs.lever.co/culture-amp/abc-123", _client(handler))
    assert job["company"] == "Culture Amp"
    assert "## Requirements" in job["description"] and "Python" in job["description"]
    assert job["description"].endswith("Benefits.")


def test_ashby_link_and_closed_job():
    def handler(request):
        return httpx.Response(200, json={"jobs": [
            {"id": "u-1", "title": "Eval Eng", "location": "Remote", "descriptionPlain": "Evals.",
             "jobUrl": "https://jobs.ashbyhq.com/acme/u-1"}]})
    job = lookup_job("https://jobs.ashbyhq.com/acme/u-1", _client(handler))
    assert job["title"] == "Eval Eng" and job["source"] == "ashby"
    with pytest.raises(JobLookupError, match="closed"):
        lookup_job("https://jobs.ashbyhq.com/acme/gone", _client(handler))


def test_smartrecruiters_link_strips_slug():
    def handler(request):
        assert request.url.path == "/v1/companies/QantasGroup/postings/600"
        return httpx.Response(200, json={
            "name": "PM", "company": {"name": "Qantas"}, "location": {"fullLocation": "Adelaide"},
            "jobAd": {"sections": {"jobDescription": {"title": "The role", "text": "<p>Own it.</p>"}}},
        })
    job = lookup_job("https://jobs.smartrecruiters.com/QantasGroup/600-product-manager", _client(handler))
    assert job["company"] == "Qantas" and "## The role" in job["description"]


def test_workable_link_and_short_link():
    def handler(request):
        return httpx.Response(200, json={"name": "Hugging Face", "jobs": [
            {"shortcode": "AB12", "title": "MLE", "city": "Paris", "country": "France",
             "description": "<p>Hi</p>"}]})
    job = lookup_job("https://apply.workable.com/huggingface/j/AB12/", _client(handler))
    assert job["company"] == "Hugging Face" and job["location"] == "Paris, France"
    with pytest.raises(JobLookupError, match="company"):
        lookup_job("https://apply.workable.com/j/AB12", _client(handler))


@pytest.mark.parametrize("url", [
    "https://www.linkedin.com/jobs/view/123/",
    "https://au.linkedin.com/jobs/view/x",
    "https://www.seek.com.au/job/95546926",
    "https://au.seek.com/job/1",
])
def test_linkedin_and_seek_are_never_fetched(url):
    def handler(request):
        raise AssertionError("must not fetch")
    with pytest.raises(JobLookupError, match="doesn't allow automated access"):
        lookup_job(url, _client(handler))


def test_generic_page_with_jobposting_json_ld():
    ld = {"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, {
        "@type": "JobPosting", "title": "Head of QE", "hiringOrganization": {"name": "Defence Co"},
        "jobLocation": {"address": {"addressLocality": "Adelaide", "addressRegion": "SA"}},
        "description": "<p>Lead verification.</p>"}]}
    page = f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head></html>'
    client = _client(lambda r: httpx.Response(200, html=page))
    job = lookup_job("https://careers.example.com/jobs/1", client)
    assert job == {"title": "Head of QE", "company": "Defence Co", "location": "Adelaide, SA",
                   "description": "Lead verification.", "source": "manual"}


def test_generic_page_falls_back_to_title():
    page = '<html><head><meta property="og:title" content="Quality Lead | Acme"><meta property="og:site_name" content="Acme Careers"></head></html>'
    job = lookup_job("https://acme.example/careers/9", _client(lambda r: httpx.Response(200, html=page)))
    assert job["title"] == "Quality Lead | Acme" and job["partial"] is True


def test_errors_are_user_facing():
    with pytest.raises(JobLookupError, match="https://"):
        lookup_job("not a link", _client(lambda r: httpx.Response(200)))
    with pytest.raises(JobLookupError, match="closed"):
        lookup_job("https://jobs.lever.co/acme/x", _client(lambda r: httpx.Response(404)))
    def boom(request):
        raise httpx.ConnectError("nope")
    with pytest.raises(JobLookupError, match="Couldn't reach"):
        lookup_job("https://example.com/job", _client(boom))


ATS_PAGE_NO_JOB_DATA = """<html><head><title>ATO Careers - Deputy Commissioner, Digital Delivery</title></head>
<body>
<nav><ul><li>Home</li><li>Search jobs</li><li>Log in to your careers account today</li></ul></nav>
<h1>Deputy Commissioner, Digital Delivery</h1>
<div class="cp_message"><ul><li>To proceed, please enable JavaScript in your internet browser.</li></ul></div>
<div class="cp_content">
  <ul><li>$346,137 to $390,916 total remuneration package</li><li>Various locations in ACT, NSW, QLD, SA and VIC.</li></ul>
  <div class="body">
    <p>We are seeking an experienced and exceptional leader and information technology professional to join the executive team.</p>
    <p>You will lead a large, geographically dispersed workforce and set strategic direction across a portfolio of digital products.</p>
    <p>You will be the principal adviser on digital delivery and transformation, influencing decisions across government.</p>
  </div>
</div>
<footer><p>Accessibility statement and privacy policy for the careers site and related services.</p></footer>
<script>var tracking = "lots of words that are not content at all whatsoever";</script>
</body></html>"""


def test_generic_page_without_job_data_reads_main_content():
    job = lookup_job("https://ato.nga.net.au/cp/index.cfm?event=jobs.jati&jobID=X",
                     _client(lambda r: httpx.Response(200, html=ATS_PAGE_NO_JOB_DATA)))
    assert job["title"] == "Deputy Commissioner, Digital Delivery"
    assert job["company"] == "ATO"
    assert "partial" not in job
    d = job["description"]
    assert d.startswith("- $346,137 to $390,916")
    assert "principal adviser on digital delivery" in d
    for noise in ("Search jobs", "enable JavaScript", "Accessibility statement", "tracking"):
        assert noise not in d
