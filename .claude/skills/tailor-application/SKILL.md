---
name: tailor-application
description: Write a tailored resume and cover letter for a job on the Job Search Buddy board, from the candidate's profile and the posting, and save them where the dashboard shows them. Use whenever the user asks to tailor, write or draft a resume, CV or cover letter for a job, to "process the tailoring queue", or to "help me apply to <job>", even if they don't say "tailor".
---

# Tailor an application

Each job lives in `jobs/<id>/`. Its page on the dashboard shows
`tailored_resume.md` / `.pdf` and `cover_letter.md` / `.pdf` from that
folder in tabs, with buttons to copy the text or download the PDF.

## 1. Which jobs

- "tailor my applications", "process the tailoring queue":
  `.venv/bin/python -m app.cli pending` → lines tagged `needs_tailoring`
  (set by the **Request tailoring** button on a job's page).
- A named job or key (e.g. `0da08023`): the folder in `jobs/` whose name
  starts with it.

If nothing is queued, say so and explain the Request tailoring button.

## 2. Read

- `profile/profile.md`, the only source of facts about the candidate.
- `jobs/<id>/posting.md`, the job.
- The job's score rationale, if it has one (shown on the job page and in
  the database), for the gaps to address.

## 3. Write

**Never invent anything.** Use only what the profile states: no new
employers, titles, dates, numbers, qualifications or skills, and no
upgrading "contributed" to "led". Tailoring means choosing, ordering and
phrasing true material to fit the job. If the posting asks for something the
profile lacks, leave it out and mention the gap in your report, so the user
can add it to their profile if it's true.

- **`tailored_resume.md`**: `# Name`, a contact line, a 2-3 line summary
  aimed at this role, then `## Experience` (most relevant bullets first,
  outcomes first), `## Skills` (the posting's must-haves that the profile
  supports, using the posting's wording where accurate), `## Education`.
  Aim for one to two pages.
- **`cover_letter.md`**: under 350 words. Why this company and role, two
  or three specific pieces of evidence from the profile matched to the
  posting's needs, and a short close. No clichés ("I am writing to express
  my interest").

Write in the language and spelling of the posting (e.g. UK vs US English).

## 4. Save and record

```bash
.venv/bin/python scripts/md_to_pdf.py jobs/<id>/tailored_resume.md jobs/<id>/tailored_resume.pdf
.venv/bin/python scripts/md_to_pdf.py jobs/<id>/cover_letter.md jobs/<id>/cover_letter.pdf
.venv/bin/python -m app.cli tailor <id> jobs/<id>/tailored_resume.md jobs/<id>/cover_letter.md
```

The last command clears the job's "needs tailoring" flag.

## 5. Report

For each job: what you emphasised, any gaps you couldn't cover from the
profile, and a reminder to read the documents on the job's page before
sending them. They should check every claim, because the applications go
out under their name.
