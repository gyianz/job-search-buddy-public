---
name: setup
description: First-time setup of Job Search Buddy for a new user, start to finish, including people who have never used a terminal. Use whenever the user has just downloaded or cloned this repo, or says anything like "set this up for me", "get started", "install this", "how do I start", "open the dashboard", "it won't start", or asks what to do first, even if they don't say "setup".
---

# Set up Job Search Buddy

Assume the user is not technical. Do the technical work yourself, explain
each step in one plain sentence, and never ask them to type commands. Say
"the dashboard" rather than "the server", and "your settings" rather than
file names, unless they ask.

Work from the repo root. Check each step before doing it, so running this
again on a half-set-up copy is safe.

## 1. Install

1. Check for Python 3.10 or newer (`python3 --version`). If it's missing or
   too old, tell them how to get it for their system in one or two
   sentences (on a Mac: the installer from python.org, or
   `brew install python@3.12` if they already use Homebrew). Wait for them
   to say it's done, then check again.
2. Create the virtual environment and install the packages, if `.venv/`
   doesn't exist yet:
   `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`.
3. If `profile/profile.md` is missing, copy it from
   `profile/profile.example.md`. Create the `jobs/` and `data/` folders.
4. Run `.venv/bin/pytest -q` as a quick health check. If anything fails,
   fix the cause if it's an install problem; otherwise tell them plainly
   what doesn't work.

On Windows without WSL, `scripts/run_server.sh` won't run. Start the
dashboard with `.venv\Scripts\uvicorn app.main:create_app --factory`
instead, and use `.venv\Scripts\python` wherever these skills say
`.venv/bin/python`.

## 2. Start the dashboard

Start it with `scripts/run_server.sh` as a background process, then
tell the user to open http://127.0.0.1:8000. If the in-app browser is
available, open it there for them. If port 8000 is taken, use `PORT=8001`.

Tell them that on a Mac, next time they can double-click
**Start Job Search Buddy.command** in the folder instead of asking you. The
first time, macOS warns that Apple "could not verify" it (it does this for
any unsigned script from the internet). To allow it: click **Done**, open
**System Settings** → **Privacy & Security**, scroll down, click **Open
Anyway** and confirm. Don't remove the quarantine flag or change security
settings for them; that's their decision. If they'd rather not, they can
keep asking you to "open the dashboard".

## 3. Build their profile

Everything else depends on the profile, so do this next. Ask for their
resume. They can drag the file into the chat, or paste the text. Then
follow the `seed-profile` skill to fill in `profile/profile.md`, including
**Target Roles & Preferences**: the roles they want, seniority, location,
salary and deal-breakers.

If they'd rather type it themselves, show them the **Profile** page, where
every section has an Edit button.

## 4. Make the rubric theirs

The rubric starts as a generic example. If `profile/rubric.json` doesn't
exist yet, create it from the default:
`.venv/bin/python -c "from app.rubric import DEFAULT_RUBRIC, save_rubric; save_rubric(DEFAULT_RUBRIC)"`.
Then, using what they told you about target roles and preferences, propose
changes to it:

- deal-breakers: their hard noes (location, contract, industries, level);
- target role families (match) and adjacent ones (stretch);
- the salary criterion's five bands, in their currency, and whether they
  mean base or package.

Show the proposal as a short list, and write it only after they agree.
Remind them that they can change anything later on the **Rubric** page.

## 5. Choose job boards

Ask which companies they're interested in, and where they want to work.
`seed_companies.example.json` has a few starter companies in the right
format; there's no `seed_companies.json` until you create one, so nothing is
fetched before the user has chosen.
For each company, find its careers page and check whether it uses
Greenhouse, Lever, Ashby, SmartRecruiters or Workable (the board URL
patterns are in the README). Add the ones that work on the **Job boards**
page or in `seed_companies.json`, with `title_keywords` for their kind of
role and `location_keywords` for where they want to work. Only copy over
starter companies they actually want. Keep the keywords specific: broad
words like "engineer" can pull in hundreds of jobs from one large company.

Companies on other systems (Workday, LinkedIn only, etc.) can't be fetched
automatically. Tell them they can still add any job by pasting its link
with the **+ Add job** button on the board.

## 6. First fetch and scoring

Run `.venv/bin/python -m app.cli fetch`, say how many jobs came in, then
offer to score them with the `score-jobs` skill. If there are many, offer
to score the first 10-15 so they can check the scores feel right before
doing the rest.

## 7. Hand over

Finish with a short "how to use it from now on" list, in their words:

- **Find new jobs:** "fetch new jobs", or the **Fetch new postings** button on the board.
- **Score them:** "score my jobs".
- **Apply:** open a job, click **Request tailoring**, then say "tailor my
  applications" (or "write a resume for <job>").
- **Track progress:** drag cards between columns on the board.
- **Update what it knows about you:** the Profile page, or tell Claude.

Mention that their profile, jobs and documents stay on their computer. They
are not uploaded anywhere, except what's sent to Claude while it works.
