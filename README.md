# Job Search Buddy

A personal job-search dashboard that runs on your own computer, with Claude
as your assistant. It:

- **finds jobs** from the careers pages of companies you choose, and lets
  you add any other job by pasting its link;
- **scores every job** against what you want (your "rubric") and what you
  bring (your profile), so the best matches are at the top;
- **writes a tailored resume and cover letter** for the jobs you pick,
  using only facts from your profile;
- **tracks your applications** on a board you drag cards across.

Your profile, jobs and documents stay on your computer. The dashboard never
calls an AI model itself: scoring and writing happen when you ask Claude.

## Getting started (no coding needed)

You need:

- a Mac (Linux works too; on Windows, Claude can set it up but the
  double-click launcher is Mac-only);
- the [Claude desktop app](https://claude.ai/download), on a plan that
  includes Claude Code.

Then:

1. **Get your own copy.** On this page, click **Use this template** →
   **Create a new repository**, and make it **Private** (it will hold your
   resume). Or, without a GitHub account, click **Code** → **Download ZIP**
   and unzip it somewhere you'll find it, such as your Documents folder.
2. **Open it in Claude.** In the Claude desktop app, go to the **Code** tab,
   start a new session and choose the folder you just unzipped (or cloned).
3. **Say "Set this up for me."** Claude installs what's needed, starts the
   dashboard, and then helps you:
   - build your profile from your resume (drag the file into the chat);
   - set your rubric: the roles you want, your deal-breakers, your salary;
   - choose which companies' job boards to watch;
   - fetch and score your first jobs.

After that, everyday use is just asking:

| You want to… | Say to Claude, or do on the dashboard |
|---|---|
| Open the dashboard | Double-click **Start Job Search Buddy.command**, or say "open the dashboard" |
| Find new jobs | "Fetch new jobs", or **Fetch new postings** on the board |
| Add a job you found elsewhere | **+ Add job** on the board, then paste its link |
| Score jobs | "Score my jobs" |
| Apply for a job | Click **Request tailoring** on the job, then say "tailor my applications" |
| Track applications | Drag cards between columns on the board |
| Update what it knows about you | The **Profile** page, or "add this to my profile" |
| Change how jobs are judged | The **Rubric** page |

The first time you double-click the launcher, macOS may say it can't be
opened. Right-click it, choose **Open**, then **Open** again; after that a
double-click works.

**Always read a tailored resume or cover letter before sending it.** Claude
is told never to invent experience, but the application goes out under your
name.

### Keeping your data private

Your profile, rubric, job board list, jobs and the database are listed in
`.gitignore`, so they're never committed, even if you later publish your
copy. If your copy is a private repository and you'd like their history in
git, delete those lines from `.gitignore`.

## How it works

The dashboard and CLI are plain, predictable code: there is no AI client and
no API key anywhere in `app/`. All judgment (scoring a posting as
match/stretch/no-fit, writing a tailored resume or cover letter) happens in
a Claude Code session, guided by the skills in `.claude/skills/`:

- `setup`: first-time setup for a new user;
- `seed-profile`: builds and updates `profile/profile.md`;
- `score-jobs`: scores jobs against the rubric and records the results;
- `tailor-application`: writes the resume and cover letter for a job.

The web app only displays and edits what's in the database and these files.

## Technical details

### Setup

Requires Python 3.10 or newer. `scripts/run_server.sh` creates the virtualenv
on first run, or you can set it up yourself:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

### Running the dashboard

```bash
scripts/run_server.sh
```

Set `HOST` or `PORT` to change the bind address (default `127.0.0.1:8000`).

This serves the dashboard (job list, statuses, scores) for browsing what's
in the queue. It reads from `data/app.db` (SQLite, created automatically,
git-ignored) and does not write anything you need to hand-edit.

Set the `JSB_DB_PATH` environment variable to override the database path
(used by both the dashboard and the CLI below, so they stay in sync).

Besides the board, the top navigation has:

- **Profile**: `profile/profile.md` rendered section by section, i.e. what
  scoring and tailoring know about you. Edit, add or delete sections in
  place, or edit the whole file as markdown. If the file changed since you
  opened the page (e.g. Claude updated it), the save is refused and your
  edit is kept so nothing is overwritten.
- **Job boards**: how many company boards `fetch` pulls from (per platform),
  their filters and how many jobs each has produced. Connect a new board
  (with a *Test connection* button that checks the token live) or remove
  one; this edits `seed_companies.json`.
- **Rubric**: the LLM-as-judge rubric Claude scores against: deal-breakers,
  target role families, stretch examples, and the 1-5 criteria with their
  scales. Add, edit or remove any of them, and edit the rationale guide;
  this edits `profile/rubric.json`. A criterion's key can't be renamed,
  since scores are stored against it. After
  adding a criterion, the page offers to queue already-scored jobs for
  re-scoring.

### The CLI (Claude Code side of the workflow)

The CLI is the other half of the workflow — the commands a Claude Code
session runs to move jobs through the queue:

```bash
.venv/bin/python -m app.cli fetch
# Fetches new postings from the configured companies (see seed_companies.json)
# and inserts them into the database.

.venv/bin/python -m app.cli pending
# Lists jobs that still need scoring or tailoring.

.venv/bin/python -m app.cli rubric
# Prints the scoring rubric (profile/rubric.json) as markdown. Read it before
# scoring.

.venv/bin/python -m app.cli score <job_id> <match|stretch|no_fit> \
    --change N --skills N --seniority N --salary N \
    --salary-estimate '<text>' '<rationale>'
# Records a score and rationale for a job. This is where human/Claude
# judgment about fit enters the system — the CLI itself does no scoring.
# There is one --<key> flag (1-5) per criterion in the rubric, so the flags
# change when criteria are added or removed (see `score --help`).

.venv/bin/python -m app.cli tailor <job_id> <resume_path> <cover_letter_path>
# Records the paths to a tailored resume and cover letter you (with Claude)
# wrote for this job.
```

The typical flow: run `fetch` to pull in new postings, run `pending` to see
what needs attention, then — in a Claude Code conversation, using your
`profile/profile.md` and the posting text as context — decide on a score and
draft tailored documents, recording the results back with `score` and
`tailor`.

### Your settings files

These files hold your settings. Edit them by hand, through Claude, or from
the dashboard:

- **`profile/profile.md`** — your background, skills, experience,
  achievements, and target-role preferences. This is the context fed into
  scoring and tailoring decisions. Grow it over time as you think of more
  detail to add. Edited from the Profile page; the CLI only reads it.
- **`profile/rubric.json`** — the scoring rubric: bucket rules
  (`deal_breakers`, `match_families`, `stretch_examples`), the
  `rationale_guide`, and the `criteria` (each with a `key`, labels and five
  `levels` describing scores 5 down to 1). Edited from the Rubric page.
  Criteria scores are stored per key, so removing a criterion hides its
  scores and re-adding the same key brings them back.
- **`seed_companies.json`** — the list of companies that `app.cli fetch`
  pulls postings from (start from `seed_companies.example.json`). Edited
  from the Job boards page, or by hand. Each entry names a `platform` and
  the company's `token` on it:

  | platform          | token is the `<x>` in…                      |
  |-------------------|---------------------------------------------|
  | `greenhouse`      | `boards.greenhouse.io/<x>`                  |
  | `lever`           | `jobs.lever.co/<x>`                         |
  | `ashby`           | `jobs.ashbyhq.com/<x>`                      |
  | `smartrecruiters` | `jobs.smartrecruiters.com/<x>` (case matters) |
  | `workable`        | `apply.workable.com/<x>`                    |

  Optional `title_keywords` / `location_keywords` lists keep only postings
  whose title / location contains one of the keywords.

### The jobs/ folder

Every posting lives in `jobs/<id>/posting.md`, alongside
any `tailored_resume.*` / `cover_letter.*` written for it. A job's page has
tabs for these: the markdown is shown as a formatted page (with *Copy text*
for pasting into application forms) and the PDF can be opened or downloaded.
The dashboard and CLI load any folder that isn't in the database yet, so a
fresh checkout shows every saved listing, and you can add a posting from
anywhere (LinkedIn, SEEK, a recruiter email) by creating a folder whose
`posting.md` starts with:

```markdown
# <Job title>

**Company:** <Company>
**Location:** <Location>
**Source URL:** <link to the posting>
```

Set `JSB_JOBS_DIR` to use a different folder. Likewise `JSB_PROFILE_PATH`,
`JSB_RUBRIC_PATH` and `JSB_SEED_PATH` override where the profile, rubric and
board list are read from.

### Tests

```bash
.venv/bin/pytest -v
```
