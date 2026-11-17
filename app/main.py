import os
import re
from datetime import datetime
from urllib.parse import quote, urlencode
from pathlib import Path

import httpx
from fastapi import FastAPI, Form, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates

from app.db import (
    connect,
    delete_job,
    get_job,
    init_db,
    list_jobs,
    set_needs_scoring,
    set_needs_tailoring,
    update_status,
)
from app import boards as boards_mod
from app import profile as profile_mod
from app import rubric as rubric_mod
from app.ats.fetch import FETCHERS, _matches_filters, fetch_all
from app.ats.lookup import JobLookupError, lookup_job
from app.jobs_folder import add_job, sync_jobs_folder
from app.markdown import render as render_markdown, split_sections
from app.storage import move_to_trash

TEMPLATES_DIR = Path(__file__).parent / "templates"



def _with_total(job: dict, criteria: list[tuple[str, str, str]]) -> dict:
    """Add score_total: the sum of the rubric's criteria this job has scores for.

    score_max is 5 per criterion in the rubric; criteria added after a job was
    scored count as missing until it's re-scored.
    """
    scores = job.get("criteria_scores") or {}
    values = [scores[key] for key, _, _ in criteria if key in scores]
    job["score_total"] = sum(values) if values else None
    job["score_max"] = 5 * len(criteria)
    job["score_missing"] = [label for key, _, label in criteria if key not in scores]
    return job

# Tailored documents a job folder can hold: (tab id, label, file stem).
# Each may exist as .md (shown on the job page) and/or .pdf (opened/downloaded).
DOCUMENTS = [
    ("resume", "Tailored resume", "tailored_resume"),
    ("cover-letter", "Cover letter", "cover_letter"),
]
_DOC_FILES = {f"{stem}{ext}" for _, _, stem in DOCUMENTS for ext in (".md", ".pdf")}

# Board columns, in workflow order: (status value, column title).
BOARD_COLUMNS = [
    ("new", "New"),
    ("interested", "Interested"),
    ("applied", "Applied"),
    ("interviewing", "Interviewing"),
    ("rejected", "Rejected"),
    ("not_interested", "Not interested"),
    ("passed", "Passed"),
]

# Within a column, show best-fit jobs first.
# Unscored jobs (missing from this map) sort between stretch and no_fit.
_SCORE_ORDER = {"match": 0, "stretch": 1, "no_fit": 3}


def _wants_json(request: Request) -> bool:
    return "application/json" in request.headers.get("accept", "")


def create_app(
    db_path: str | None = None,
    jobs_dir: str | None = None,
    seed_path: str | None = None,
    rubric_path: str | None = None,
    profile_path: str | None = None,
) -> FastAPI:
    if db_path is None:
        db_path = os.environ.get("JSB_DB_PATH", "data/app.db")
    if jobs_dir is None:
        jobs_dir = os.environ.get("JSB_JOBS_DIR", "jobs")
    app = FastAPI()
    app.state.db_path = db_path
    app.state.jobs_dir = Path(jobs_dir)
    app.state.seed_path = Path(seed_path) if seed_path else boards_mod.seed_path()
    app.state.rubric_path = Path(rubric_path) if rubric_path else rubric_mod.rubric_path()
    app.state.profile_path = Path(profile_path) if profile_path else profile_mod.profile_path()
    templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

    conn = connect(app.state.db_path)
    try:
        init_db(conn)
    finally:
        conn.close()

    def _criteria() -> list[tuple[str, str, str]]:
        return rubric_mod.criteria_labels(rubric_mod.load_rubric(app.state.rubric_path))

    @app.get("/")
    def dashboard(request: Request, show_closed: bool = False):
        conn = connect(app.state.db_path)
        try:
            # Pick up postings saved to jobs/ since the last page load.
            sync_jobs_folder(conn, app.state.jobs_dir)
            jobs = list_jobs(conn, include_closed=show_closed)
        finally:
            conn.close()

        columns = {status: [] for status, _ in BOARD_COLUMNS}
        for job in jobs:
            columns.setdefault(job["status"], []).append(job)
        criteria = _criteria()
        for cards in columns.values():
            for job in cards:
                _with_total(job, criteria)
            # Bucket first, then highest criteria total; the stable sort keeps
            # newest-first order among equals.
            cards.sort(key=lambda j: (
                _SCORE_ORDER.get(j.get("score_bucket"), 2),
                -(j["score_total"] or 0),
            ))

        companies = sorted({job["company"] for job in jobs})

        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {
                "board_columns": BOARD_COLUMNS,
                "criteria": criteria,
                "columns": columns,
                "companies": companies,
                "total": len(jobs),
                "show_closed": show_closed,
            },
        )

    @app.post("/fetch")
    def fetch(request: Request):
        conn = connect(app.state.db_path)
        try:
            # Register saved postings first so fetch never rewrites them.
            sync_jobs_folder(conn, app.state.jobs_dir)
            fetch_all(conn, boards_mod.load_boards(app.state.seed_path))
        finally:
            conn.close()
        return RedirectResponse(url="/", status_code=303)

    @app.get("/job/{job_id}")
    def job_detail(request: Request, job_id: str):
        conn = connect(app.state.db_path)
        try:
            job = get_job(conn, job_id)
        finally:
            conn.close()

        if job is None:
            return Response(status_code=404)

        criteria = _criteria()
        posting_content = ""
        posting_path = job.get("posting_path")
        if posting_path:
            path = Path(posting_path)
            if path.exists():
                posting_content = path.read_text()

        folder = app.state.jobs_dir / job_id
        documents = []
        for tab, label, stem in DOCUMENTS:
            md, pdf = folder / f"{stem}.md", folder / f"{stem}.pdf"
            if not (md.exists() or pdf.exists()):
                continue
            text = md.read_text() if md.exists() else ""
            documents.append({
                "tab": tab, "label": label, "stem": stem,
                "text": text, "html": render_markdown(text) if text else "",
                "has_md": md.exists(), "has_pdf": pdf.exists(),
                "path": str(md if md.exists() else pdf),
            })

        return templates.TemplateResponse(
            request,
            "job_detail.html",
            {
                "documents": documents,
                "job": _with_total(job, criteria),
                "posting_content": posting_content,
                "statuses": BOARD_COLUMNS,
                "criteria": criteria,
            },
        )

    @app.get("/job/{job_id}/docs/{filename}")
    def job_document(job_id: str, filename: str, download: bool = False):
        """Serve a tailored resume / cover letter (.md or .pdf) from the job's folder."""
        # Only the known document names, and only a plain job id: no path tricks.
        if filename not in _DOC_FILES or not re.fullmatch(r"[0-9a-f]{6,64}", job_id):
            return Response(status_code=404)
        path = app.state.jobs_dir / job_id / filename
        if not path.is_file():
            return Response(status_code=404)
        conn = connect(app.state.db_path)
        try:
            job = get_job(conn, job_id)
        finally:
            conn.close()
        name = filename
        if job:
            # e.g. "Tailored resume - Acme - AI Eval Lead.pdf" rather than tailored_resume.pdf
            label = dict((stem, lbl) for _, lbl, stem in DOCUMENTS)[filename.rsplit(".", 1)[0]]
            safe = re.sub(r"[^\w .,&()-]+", "", f"{label} - {job['company']} - {job['title']}")[:150]
            name = f"{safe}.{filename.rsplit('.', 1)[1]}"
        media = "application/pdf" if filename.endswith(".pdf") else "text/markdown; charset=utf-8"
        return FileResponse(
            path, media_type=media, filename=name,
            content_disposition_type="attachment" if download else "inline",
        )

    @app.post("/job/{job_id}/status")
    def set_status(request: Request, job_id: str, status: str = Form(...)):
        conn = connect(app.state.db_path)
        try:
            update_status(conn, job_id, status)
            job = get_job(conn, job_id)
            # Showing interest in an unscored job queues it for scoring.
            if status == "interested" and not job["score_bucket"] and not job["needs_scoring"]:
                set_needs_scoring(conn, job_id)
                job["needs_scoring"] = 1
        except ValueError as exc:
            if "no job with id" in str(exc):
                return Response(status_code=404)
            return Response(status_code=400)
        finally:
            conn.close()
        if _wants_json(request):
            # The board's drag-and-drop updates status in place.
            return JSONResponse(
                {"id": job_id, "status": status, "needs_scoring": bool(job["needs_scoring"])}
            )
        return RedirectResponse(url=f"/job/{job_id}", status_code=303)

    def _origin(request: Request) -> str:
        return str(request.base_url).rstrip("/")

    def _companies() -> list[str]:
        conn = connect(app.state.db_path)
        try:
            return [r[0] for r in conn.execute("SELECT DISTINCT company FROM jobs ORDER BY company")]
        finally:
            conn.close()

    @app.get("/bookmarklet")
    def bookmarklet(request: Request):
        origin = _origin(request)
        source = templates.get_template("bookmarklet.js").render(origin=origin)
        link = "javascript:" + quote(source.strip(), safe="")
        return templates.TemplateResponse(
            request, "bookmarklet.html", {"bookmarklet": link, "origin": origin}
        )

    @app.get("/jobs/new")
    def new_job(request: Request):
        """Standalone Add job page; the bookmarklet opens it pre-filled."""
        return templates.TemplateResponse(request, "add_job.html", {"companies": _companies()})

    @app.get("/jobs/lookup")
    def lookup(url: str = ""):
        """Read a job link so the Add job form can be pre-filled."""
        conn = connect(app.state.db_path)
        try:
            row = conn.execute("SELECT id FROM jobs WHERE url = ?", (url.strip(),)).fetchone()
        finally:
            conn.close()
        if row:
            return JSONResponse({"existing": row[0]})
        try:
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                job = lookup_job(url, client)
        except JobLookupError as exc:
            return JSONResponse({"error": str(exc)}, status_code=422)
        return JSONResponse(job)

    @app.post("/jobs/add")
    def add(
        request: Request,
        title: str = Form(""),
        company: str = Form(""),
        location: str = Form(""),
        url: str = Form(""),
        description: str = Form(""),
        interested: bool = Form(False),
    ):
        conn = connect(app.state.db_path)
        try:
            try:
                job_id, created = add_job(
                    conn,
                    company=company,
                    title=title,
                    url=url,
                    location=location,
                    description=description,
                    base=app.state.jobs_dir,
                )
            except ValueError as exc:
                if _wants_json(request):
                    return JSONResponse({"error": str(exc)}, status_code=400)
                return Response(str(exc), status_code=400)
            if created and interested:
                # Same as dragging it to Interested: queue it for scoring.
                update_status(conn, job_id, "interested")
                set_needs_scoring(conn, job_id)
        finally:
            conn.close()
        if _wants_json(request):
            return JSONResponse({"id": job_id, "created": created})
        return RedirectResponse(url=f"/job/{job_id}", status_code=303)

    @app.post("/job/{job_id}/delete")
    def delete(request: Request, job_id: str):
        conn = connect(app.state.db_path)
        try:
            delete_job(conn, job_id)
        except ValueError:
            return Response(status_code=404)
        finally:
            conn.close()
        # Keep the files (recoverable) but out of jobs/, so neither the folder
        # sync nor the next fetch brings the job back.
        move_to_trash(job_id, app.state.jobs_dir)
        if _wants_json(request):
            return JSONResponse({"id": job_id, "deleted": True})
        return RedirectResponse(url="/", status_code=303)

    @app.post("/job/{job_id}/request-scoring")
    def request_scoring(job_id: str):
        conn = connect(app.state.db_path)
        try:
            set_needs_scoring(conn, job_id)
        except ValueError:
            return Response(status_code=404)
        finally:
            conn.close()
        return RedirectResponse(url=f"/job/{job_id}", status_code=303)

    @app.post("/job/{job_id}/request-tailoring")
    def request_tailoring(job_id: str):
        conn = connect(app.state.db_path)
        try:
            set_needs_tailoring(conn, job_id)
        except ValueError:
            return Response(status_code=404)
        finally:
            conn.close()
        return RedirectResponse(url=f"/job/{job_id}", status_code=303)

    # ---- Profile -------------------------------------------------------

    def _profile_page(
        request: Request, notice: str = "", error: str = "", edit: str = "",
        form: dict | None = None, saved: str = "", status_code: int = 200,
    ):
        """edit: "" (view), "all" (whole file), "new", or a section index.

        form: the user's unsaved edit, re-shown after a conflict or error.
        """
        path = app.state.profile_path
        text = profile_mod.read(path)
        title, _ = split_sections(text)
        sections = profile_mod.sections(text)
        for section in sections:
            section["slug"] = re.sub(r"[^a-z0-9]+", "-", section["title"].lower()).strip("-")
            section["html"] = render_markdown(section["body"])
            section["bullets"] = sum(
                1 for line in section["body"].splitlines() if line.lstrip().startswith(("- ", "* "))
            )
        updated = (
            datetime.fromtimestamp(path.stat().st_mtime).strftime("%-d %b %Y, %-I:%M %p")
            if path.exists() else None
        )
        return templates.TemplateResponse(request, "profile.html", {
            "nav": "profile",
            "title": title,
            # The rubric pointer section is shown on the Rubric page instead.
            "sections": [s for s in sections if s["title"].lower() != "scoring rubric"],
            "text": text,
            "version": profile_mod.version(text),
            "path": str(path),
            "updated": updated,
            "words": len(text.split()),
            "notice": notice,
            "error": error,
            "edit": edit,
            "form": form or {},
            "saved": saved,
        }, status_code=status_code)

    @app.get("/profile")
    def profile(request: Request, edit: str = "", notice: str = "", saved: str = ""):
        return _profile_page(request, notice=notice, edit=edit, saved=saved)

    _CONFLICT = (
        "The profile changed since you opened it (maybe Claude updated it). "
        "The page now shows the latest version; your edit is kept below. "
        "Check it against the latest and save again."
    )

    def _profile_saved(notice: str, anchor: str = "") -> RedirectResponse:
        query = urlencode({"notice": notice, "saved": anchor})
        return RedirectResponse(
            url=f"/profile?{query}" + (f"#{anchor}" if anchor else ""), status_code=303)

    def _slug(title: str) -> str:
        return re.sub(r"[^a-z0-9]+", "-", " ".join(title.split()).lower()).strip("-")

    @app.post("/profile/sections/{index}/edit")
    def profile_edit_section(
        request: Request, index: int,
        version: str = Form(""), title: str = Form(""), body: str = Form(""),
    ):
        form = {"title": title, "body": body}
        try:
            profile_mod.update_section(app.state.profile_path, version, index, title, body)
        except profile_mod.ProfileConflict:
            return _profile_page(request, error=_CONFLICT, edit=str(index), form=form, status_code=409)
        except ValueError as exc:
            return _profile_page(request, error=str(exc), edit=str(index), form=form, status_code=400)
        return _profile_saved(f"Saved \u201c{' '.join(title.split())}\u201d.", _slug(title))

    @app.post("/profile/sections/{index}/delete")
    def profile_delete_section(request: Request, index: int, version: str = Form("")):
        try:
            profile_mod.delete_section(app.state.profile_path, version, index)
        except profile_mod.ProfileConflict:
            return _profile_page(
                request, error="The profile changed since you opened it, so nothing was "
                "deleted. Check the latest version below.", status_code=409)
        return _profile_saved("Section deleted.")

    @app.post("/profile/sections/add")
    def profile_add_section(
        request: Request, version: str = Form(""), title: str = Form(""), body: str = Form(""),
    ):
        form = {"title": title, "body": body}
        try:
            profile_mod.add_section(app.state.profile_path, version, title, body)
        except profile_mod.ProfileConflict:
            return _profile_page(request, error=_CONFLICT, edit="new", form=form, status_code=409)
        except ValueError as exc:
            return _profile_page(request, error=str(exc), edit="new", form=form, status_code=400)
        return _profile_saved(f"Added \u201c{' '.join(title.split())}\u201d.", _slug(title))

    @app.post("/profile/save")
    def profile_save_all(request: Request, version: str = Form(""), text: str = Form("")):
        try:
            profile_mod.replace_all(app.state.profile_path, version, text)
        except profile_mod.ProfileConflict:
            return _profile_page(request, error=_CONFLICT, edit="all", form={"text": text}, status_code=409)
        return _profile_saved("Profile saved.")

    # ---- Job boards ----------------------------------------------------

    def _job_counts() -> dict[str, int]:
        conn = connect(app.state.db_path)
        try:
            return {r[0]: r[1] for r in conn.execute(
                "SELECT company, COUNT(*) FROM jobs GROUP BY company")}
        finally:
            conn.close()

    @app.get("/boards")
    def boards(request: Request, error: str = "", added: str = "", removed: str = ""):
        entries = boards_mod.load_boards(app.state.seed_path)
        counts = _job_counts()
        by_platform = {key: 0 for key in boards_mod.PLATFORMS}
        for entry in entries:
            by_platform[entry.get("platform")] = by_platform.get(entry.get("platform"), 0) + 1
            entry["url"] = boards_mod.board_url(entry)
            entry["jobs"] = counts.get(entry.get("name"), 0)
        return templates.TemplateResponse(request, "boards.html", {
            "nav": "boards",
            "boards": entries,
            "platforms": boards_mod.PLATFORMS,
            "by_platform": by_platform,
            "path": str(app.state.seed_path),
            "error": error,
            "added": added,
            "removed": removed,
        })

    def _back(path: str, **params: str) -> RedirectResponse:
        query = urlencode({k: v for k, v in params.items() if v})
        return RedirectResponse(url=f"{path}?{query}" if query else path, status_code=303)

    @app.post("/boards/add")
    def boards_add(
        name: str = Form(""), platform: str = Form(""), token: str = Form(""),
        title_keywords: str = Form(""), location_keywords: str = Form(""),
    ):
        entries = boards_mod.load_boards(app.state.seed_path)
        try:
            entry = boards_mod.add_board(
                entries, name, platform, token, title_keywords, location_keywords)
        except ValueError as exc:
            return _back("/boards", error=str(exc))
        boards_mod.save_boards(entries, app.state.seed_path)
        return _back("/boards", added=entry["name"])

    @app.post("/boards/remove")
    def boards_remove(platform: str = Form(""), token: str = Form("")):
        entries = boards_mod.load_boards(app.state.seed_path)
        try:
            entry = boards_mod.remove_board(entries, platform, token)
        except ValueError as exc:
            return _back("/boards", error=str(exc))
        boards_mod.save_boards(entries, app.state.seed_path)
        return _back("/boards", removed=entry["name"])

    @app.get("/boards/test")
    def boards_test(
        platform: str = "", token: str = "",
        title_keywords: str = "", location_keywords: str = "",
    ):
        """Check a board token works, without saving anything."""
        fetcher = FETCHERS.get(platform)
        if fetcher is None or not token.strip():
            return JSONResponse({"error": "pick a platform and enter a token"}, status_code=400)
        try:
            with httpx.Client(timeout=20, follow_redirects=True) as client:
                postings = fetcher(token.strip().strip("/"), client)
        except Exception as exc:  # network errors, 404 for a wrong token, bad JSON
            return JSONResponse({"error": f"couldn't read that board: {exc}"}, status_code=422)
        entry = {
            "title_keywords": boards_mod._keywords(title_keywords),
            "location_keywords": boards_mod._keywords(location_keywords),
        }
        kept = [p for p in postings if _matches_filters(p["title"], p["location"], entry)]
        return JSONResponse({
            "total": len(postings),
            "matching": len(kept),
            "sample": [p["title"] for p in kept[:5]],
        })

    # ---- Rubric --------------------------------------------------------

    def _load_rubric() -> dict:
        return rubric_mod.load_rubric(app.state.rubric_path)

    def _save_rubric(rubric: dict) -> None:
        rubric_mod.save_rubric(rubric, app.state.rubric_path)

    def _rubric_page(
        request: Request, error: str = "", notice: str = "", added: str = "",
        form_id: str = "", form: dict | None = None, status_code: int = 200,
    ):
        """form_id/form: the add form that failed, re-shown open with its values."""
        data = _load_rubric()
        keys = [c["key"] for c in data["criteria"]]
        conn = connect(app.state.db_path)
        try:
            scored = [
                job for job in list_jobs(conn, include_closed=True) if job["score_bucket"]
            ]
        finally:
            conn.close()
        incomplete = [
            job for job in scored if any(k not in job["criteria_scores"] for k in keys)
        ]
        return templates.TemplateResponse(request, "rubric.html", {
            "nav": "rubric",
            "rubric": data,
            "rule_lists": rubric_mod.RULE_LISTS,
            "rationale_html": render_markdown(data.get("rationale_guide", "")),
            "path": str(app.state.rubric_path),
            "scored": len(scored),
            "incomplete": len(incomplete),
            "incomplete_queued": sum(1 for j in incomplete if j["needs_scoring"]),
            "error": error,
            "notice": notice,
            "added": added,
            "form_id": form_id,
            "form": form or {},
        }, status_code=status_code)

    @app.get("/rubric")
    def rubric(request: Request, error: str = "", notice: str = "", added: str = ""):
        return _rubric_page(request, error=error, notice=notice, added=added)

    def _added(notice: str, anchor: str) -> RedirectResponse:
        # Land on the new item (highlighted) rather than the top of the page.
        query = urlencode({"notice": notice, "added": anchor})
        return RedirectResponse(url=f"/rubric?{query}#{anchor}", status_code=303)

    @app.post("/rubric/rules/{list_key}/add")
    def rubric_add_rule(
        request: Request, list_key: str, title: str = Form(""), detail: str = Form(""),
    ):
        data = _load_rubric()
        try:
            rubric_mod.add_rule(data, list_key, title, detail)
        except ValueError as exc:
            return _rubric_page(
                request, error=str(exc), form_id=f"add-{list_key}",
                form={"title": title, "detail": detail}, status_code=400,
            )
        _save_rubric(data)
        index = len(data[list_key]) - 1
        return _added(f"Added \u201c{title.strip()}\u201d.", f"rule-{list_key}-{index}")

    @app.post("/rubric/rules/{list_key}/{index}/edit")
    def rubric_edit_rule(
        request: Request, list_key: str, index: int,
        original_title: str = Form(""), title: str = Form(""), detail: str = Form(""),
    ):
        data = _load_rubric()
        rules = data.get(list_key, [])
        form_id = f"edit-rule-{list_key}-{index}"
        form = {"title": title, "detail": detail}
        # The original title guards against editing the wrong rule if the file changed.
        if not 0 <= index < len(rules) or rules[index]["title"] != original_title:
            return _rubric_page(
                request, error="That rule changed since the page loaded; reload and try again.",
                status_code=409)
        try:
            rubric_mod.update_rule(data, list_key, index, title, detail)
        except ValueError as exc:
            return _rubric_page(request, error=str(exc), form_id=form_id, form=form, status_code=400)
        _save_rubric(data)
        return _added(f"Saved \u201c{title.strip()}\u201d.", f"rule-{list_key}-{index}")

    @app.post("/rubric/rules/{list_key}/remove")
    def rubric_remove_rule(list_key: str, index: int = Form(...), title: str = Form("")):
        data = _load_rubric()
        rules = data.get(list_key, [])
        # The title guards against removing the wrong rule if the file changed.
        if not 0 <= index < len(rules) or rules[index]["title"] != title:
            return _back("/rubric", error="That rule changed since the page loaded; try again.")
        rubric_mod.remove_rule(data, list_key, index)
        _save_rubric(data)
        return _back("/rubric", notice=f"Removed \u201c{title}\u201d.")

    @app.post("/rubric/criteria/add")
    def rubric_add_criterion(
        request: Request,
        key: str = Form(""), label: str = Form(""), short: str = Form(""),
        description: str = Form(""), notes: str = Form(""),
        level5: str = Form(""), level4: str = Form(""), level3: str = Form(""),
        level2: str = Form(""), level1: str = Form(""),
    ):
        data = _load_rubric()
        levels = [level5, level4, level3, level2, level1]
        try:
            rubric_mod.add_criterion(data, key, label, short, description, levels, notes)
        except ValueError as exc:
            form = {"key": key, "label": label, "short": short, "description": description,
                    "notes": notes, **{f"level{5 - i}": v for i, v in enumerate(levels)}}
            return _rubric_page(
                request, error=str(exc), form_id="add-criterion", form=form, status_code=400,
            )
        _save_rubric(data)
        new_key = data["criteria"][-1]["key"]
        return _added(f"Added criterion \u201c{label.strip()}\u201d.", f"crit-{new_key}")

    @app.post("/rubric/criteria/{key}/edit")
    def rubric_edit_criterion(
        request: Request, key: str,
        label: str = Form(""), short: str = Form(""),
        description: str = Form(""), notes: str = Form(""),
        level5: str = Form(""), level4: str = Form(""), level3: str = Form(""),
        level2: str = Form(""), level1: str = Form(""),
    ):
        data = _load_rubric()
        levels = [level5, level4, level3, level2, level1]
        try:
            rubric_mod.update_criterion(data, key, label, short, description, levels, notes)
        except ValueError as exc:
            form = {"label": label, "short": short, "description": description, "notes": notes,
                    **{f"level{5 - i}": v for i, v in enumerate(levels)}}
            return _rubric_page(
                request, error=str(exc), form_id=f"edit-crit-{key}", form=form, status_code=400)
        _save_rubric(data)
        return _added(f"Saved \u201c{label.strip()}\u201d.", f"crit-{key}")

    @app.post("/rubric/rationale")
    def rubric_edit_rationale(rationale_guide: str = Form("")):
        data = _load_rubric()
        data["rationale_guide"] = rationale_guide.replace("\r\n", "\n").strip()
        _save_rubric(data)
        return _added("Saved the rationale guide.", "rationale")

    @app.post("/rubric/criteria/{key}/remove")
    def rubric_remove_criterion(key: str):
        data = _load_rubric()
        try:
            rubric_mod.remove_criterion(data, key)
        except ValueError as exc:
            return _back("/rubric", error=str(exc))
        _save_rubric(data)
        return _back("/rubric", notice=f"Removed criterion {key}. Existing scores for it are kept but no longer shown.")

    @app.post("/rubric/requeue")
    def rubric_requeue():
        """Queue scored jobs missing a score for any current criterion."""
        keys = [c["key"] for c in _load_rubric()["criteria"]]
        conn = connect(app.state.db_path)
        try:
            queued = 0
            for job in list_jobs(conn, include_closed=True):
                if (job["score_bucket"] and not job["needs_scoring"]
                        and any(k not in job["criteria_scores"] for k in keys)):
                    set_needs_scoring(conn, job["id"])
                    queued += 1
        finally:
            conn.close()
        return _back("/rubric", notice=f"Queued {queued} job{'s' if queued != 1 else ''} for re-scoring.")

    return app
