---
name: seed-profile
description: Build out or update profile/profile.md, the candidate profile that job scoring and resume/cover-letter tailoring read. Use whenever the user wants to seed, fill in, grow, refresh or correct their profile — e.g. "add this to my profile", "here's my resume, update my profile", "interview me for my profile", "I forgot to mention I led X", pasted performance reviews, LinkedIn text, new skills, achievements, or changed job preferences (location, seniority, salary, role types) — even if they don't say "profile.md".
---

# Seed and grow the profile

`profile/profile.md` is the single source of truth about the candidate. Every
score (`app.cli score`) and every tailored resume or cover letter is written
from it, so anything missing here can't be used later, and anything wrong
here gets repeated in applications. The dashboard's Profile page
(`/profile`) renders it section by section, with an item count per section.

Your job is to get true, specific, evidence-backed material into it, in the
house style, without inventing anything.

## 1. Read what's there first

If `profile/profile.md` doesn't exist yet, copy it from
`profile/profile.example.md`. Lines in italics wrapped in underscores
(`_like this_`) are the example's placeholders: replace them with real
content, or delete them, as you fill each section in.

Read `profile/profile.md` in full before asking anything, so you don't ask
for what's already recorded and you can spot thin sections. Note which
sections are short or vague (a bullet with no outcome, a role with no
dates, a preferences section ending in "_More to come_").

## 2. Gather material

Work from whatever the user gives you, in this order of preference:

1. **Documents** — resumes, CVs, performance reviews, promotion cases,
   LinkedIn exports, project write-ups. Read them fully (use the pdf/docx
   skills for those formats). They're the richest and most accurate source.
2. **What they tell you** — a fact dropped in chat ("I also led the
   on-call rotation").
3. **An interview** — when the user asks to be interviewed, or a section is
   thin and they're up for it.

When interviewing, ask **2–3 questions at a time**, not a long
questionnaire, and aim each at a gap you found in step 1. Push gently for
the specifics that make a bullet usable in an application:

- *What changed because of you?* Numbers beat adjectives: before/after,
  time saved, % change, team count, users, revenue, incidents.
- *Scope*: how many teams/people/groups; who the stakeholders were.
- *Your part vs the team's*: "led", "built", "proposed" mean different things.
- *When*: dates or at least the year.

For **Target Roles & Preferences**, cover: role families wanted and not
wanted, seniority, location and work mode, salary floor/target (and whether
it's base or package), industries to avoid, contract vs permanent, and any
visa or relocation constraints.

Stop when the user wants to stop. A partial update saved now beats a
perfect one never written.

## 3. Write it in the house style

Keep the existing structure. These `##` sections are what the Profile page
and the tailoring work expect:

- `## Background` — current/last role, headline, education, contact.
- `## Skills` — one bullet per skill, phrased as a capability with context.
- `## Experience` — one block per role: `**Title, Company** (Mon YYYY - Mon YYYY)`,
  then bullets, grouped by theme for long roles.
- `## Achievements` — the 5–8 headline wins, each one sentence, pointing
  back to Experience for detail.
- `## Target Roles & Preferences` — bullets with a bold label
  (`**Location:**`, `**Seniority:**`, …).
- `## Scoring Rubric` — a short pointer to `profile/rubric.json`. Leave it
  as is; the rubric itself is edited on the dashboard's Rubric page.

Style rules, and why:

- **Only write what the user or their documents state.** Never round up a
  number, upgrade "contributed" to "led", or fill a gap with a plausible
  guess. This text ends up in real applications; a fabricated claim can
  cost the candidate an offer. If something is unclear, ask, or leave it out.
- **Lead with the outcome, then how.** "Cut product cycle time from 38 to
  12 days by building an automated regression harness" beats "Built a
  regression harness".
- **Wrap lines at ~78 characters**, `-` bullets, continuation lines indented
  two spaces — matching the file, so diffs stay readable.
- **Merge, don't duplicate.** If a new fact extends an existing bullet,
  edit that bullet. Add to Achievements only when it's a genuine headline win.
- **Plain hyphens and commas** rather than em dashes, matching the file.

The user can also edit this file on the dashboard's Profile page, so read
it again right before you write, and make targeted edits to the sections
you're changing rather than rewriting the whole file from an earlier read.
That way you never overwrite something they just saved.

## 4. Preferences that should change scoring

Some new facts are really scoring rules. If the user states a hard no
("no contract roles", "won't move to Perth"), a new target role family, or
a salary target, record it under Target Roles & Preferences **and** point
out that the rubric should match. Offer to update `profile/rubric.json`
(deal-breakers, match families, or a criterion's scale such as the salary
bands), or tell them they can do it on the dashboard's Rubric page. Don't
change the rubric without their go-ahead: it changes how every future job
is judged.

## 5. Finish

- Show a short summary of what changed, by section (e.g. "Experience: 3
  bullets added under Acme; Preferences: salary target now $160k base").
- Mention they can review and tweak it on the Profile page (`/profile`,
  refresh), where every section has an Edit button.
- Suggest re-scoring if the change affects fit (new skills, changed
  preferences): the `score-jobs` skill can re-score the board.
- `profile/profile.md` is tracked in git. Don't commit unless the user asks.
