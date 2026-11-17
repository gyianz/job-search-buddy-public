---
name: score-jobs
description: Score job postings on the job-search board (LLM-as-judge) against the rubric and profile, and record the results with app.cli score. Use whenever the user asks to process the scoring queue, score or re-score jobs, judge fit, or rank postings — e.g. "score my jobs", "process the queue", "score the new ones from today's fetch", "re-score after I changed the rubric", "is 0DA08023 a match?", "what's pending" — even if they don't mention the CLI.
---

# Score jobs

The dashboard never calls a model; scoring happens here. For each job you
read the posting, judge it against the rubric and the candidate's profile,
and record a bucket (`match` / `stretch` / `no_fit`), a 1–5 score per
criterion and a short rationale. The board sorts and colours cards from
these, so the scores directly decide what the user looks at first.

Run every command from the repo root with the project venv:
`.venv/bin/python -m app.cli …` (it uses `data/app.db`, the same database
as the dashboard).

## 1. Work out which jobs to score

| The user says | Jobs |
|---|---|
| "process the queue", "score my jobs", nothing specific | `app.cli pending` → lines tagged `needs_scoring` |
| "score the new ones", "after the fetch", "everything unscored" | `app.cli pending --unscored` → `needs_scoring` and `unscored` lines |
| a job key like `0DA08023` (as shown on cards) or a full id | that job: the folder in `jobs/` whose name starts with the key in lowercase |
| "re-score everything" / after a big profile change | every folder in `jobs/` (not `jobs/.trash/`). Confirm first if it's more than ~15 jobs |

`pending` lines look like `<id> <Company> - <Title> [needs_scoring|unscored]`.
Ignore lines that are only `needs_tailoring`; tailoring is separate.

After a rubric change, the Rubric page's "Queue them for re-scoring" button
flags affected jobs, so they show up as `needs_scoring` here.

If nothing is pending, say so and mention `--unscored` and job keys as
options. Don't go looking for work the user didn't ask for.

## 2. Load the judging context once

1. `app.cli rubric`: the bucket rules, rationale guide and criteria, as
   markdown. It's generated from `profile/rubric.json`, which the user edits
   on the dashboard, so read it fresh each session rather than relying on
   memory. The criteria and their `--<key>` flags can change.
2. `profile/profile.md`: background, skills, experience, preferences.
   Ignore its "Scoring Rubric" section; that's only a pointer to the rubric.

## 3. Judge each job

Read `jobs/<id>/posting.md` (title, company, location, source URL, then
the description). Then:

- **Bucket**: apply the rubric's steps in order and stop at the first that
  decides it. A deal-breaker makes it `no_fit` however attractive the rest
  is. When it's genuinely borderline, take the lower bucket and say why.
- **Every criterion, every job**, including `no_fit` ones. The board ranks
  jobs within a bucket by the total, and a missing criterion shows as "–".
  Score from the posting; where it's silent, take the most likely reading
  and say so in the rationale.
- **Salary**: if the rubric has a salary criterion, also pass
  `--salary-estimate`, e.g. `'$170k-$190k base (est.)'`. Follow the
  rubric's notes on base vs package and marking estimates.
- **Rationale**: follow the rubric's "Writing the rationale" guide. Be
  concrete: name the deciding rule, the specific profile experience that
  overlaps, and the real gaps. "Strong fit" tells the user nothing.

Be honest rather than generous. Inflated scores waste the user's
application effort on poor fits.

If a posting is too thin to judge (a one-line stub, an unnamed recruiter
client), still score it on what's there, say what's missing in the
rationale, and list it in your summary so the user can add the full text.

## 4. Record it

One command per job. Put the estimate and rationale in **single quotes**:
inside double quotes the shell expands `$160k` as a variable, and the
estimate is silently saved as `k-k base`.

```bash
.venv/bin/python -m app.cli score <job_id> <match|stretch|no_fit> \
  --change 3 --skills 4 --seniority 5 --salary 4 \
  --salary-estimate '$160k-$175k base (est.)' \
  'Match: AI evaluation role at the right level. ...'
```

For an apostrophe inside the rationale, write `'\''` (e.g. `'it'\''s'`) or
rephrase.

Use the full 12-character id and one `--<key>` flag for each criterion the
rubric lists (check `app.cli score --help` if unsure). The command prints
nothing on success and `error: …` on failure; on error, fix the call and
retry rather than moving on. Scoring clears the job's `needs_scoring` flag
and replaces any earlier score.

Don't change job statuses, edit postings, or touch the rubric while
scoring. Those are the user's calls.

## 5. Report

Finish with a compact table, best first, then the notes:

| Job | Company | Bucket | Total | Key reason |
|---|---|---|---|---|
| AI Eval Lead (`0da08023`) | Acme | match | 18/20 | AI eval family; LLM-as-judge experience |

Then list jobs you couldn't judge well (thin postings) and anything the
user should decide (e.g. a recurring deal-breaker that suggests a rubric
tweak). Mention they can see the results on the board, sorted by bucket and
total.
