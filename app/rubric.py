"""The scoring rubric (LLM-as-judge): bucket rules plus 1-5 criteria.

Lives in profile/rubric.json so the dashboard can add and remove rules and
criteria. `app.cli rubric` prints it as markdown for the Claude session that
does the scoring; `app.cli score` takes one `--<key>` flag per criterion.
"""
import copy
import json
import os
import re
from pathlib import Path

# Bucket rule lists, in the order they're applied: (rubric key, heading).
RULE_LISTS = [
    ("deal_breakers", "Deal-breakers → no_fit"),
    ("match_families", "Target role families → match"),
    ("stretch_examples", "Otherwise → stretch (examples)"),
]

KEY_RE = re.compile(r"^[a-z][a-z0-9_]{0,23}$")
# Keys that would clash with the score command's own options.
_RESERVED_KEYS = {"salary_estimate", "help", "h"}

DEFAULT_RUBRIC = {
    # A starting point only: the setup skill (or the Rubric page) replaces
    # these examples with the user's own rules.
    "deal_breakers": [
        {"title": "Fixed-term or contract",
         "detail": "Example: permanent roles only. Remove this if you're open to contracts."},
        {"title": "Wrong location",
         "detail": "Example: no location you can work from and no remote option. Say which "
                   "cities, countries or remote arrangements work for you."},
        {"title": "Well below your level",
         "detail": "Example: junior or graduate roles when you're experienced."},
    ],
    "match_families": [
        {"title": "Your target roles",
         "detail": "Example: the job titles and kinds of work you most want next. Replace "
                   "with your own, one family per line."},
    ],
    "stretch_examples": [
        {"title": "Adjacent roles",
         "detail": "Example: roles that use your skills but aren't your first choice."},
    ],
    "rationale_guide": (
        "Two to four sentences, in this order:\n\n"
        "1. The verdict and the deciding reason (the deal-breaker hit, or which role family "
        "it matches).\n"
        "2. Strongest overlap with the profile: name specific experience from it.\n"
        "3. Gaps or risks the application would need to address (missing domain, seniority "
        "jump, relocation, recruiter posting with an unnamed client).\n\n"
        "When the call is borderline between two buckets, choose the lower one and say why "
        "in the rationale."
    ),
    "criteria": [
        {
            "key": "change", "short": "Dir", "label": "Career direction",
            "description": "How well the role moves you towards what you want to do next.",
            "notes": "",
            "levels": [
                "Exactly the direction you want to go.",
                "Mostly in that direction.",
                "Neutral: similar to what you do now.",
                "Somewhat away from where you want to go.",
                "The kind of work you want to leave behind.",
            ],
        },
        {
            "key": "skills", "short": "Skl", "label": "Skills match",
            "description": "How much of the role needs skills already in the profile.",
            "notes": "",
            "levels": [
                "Nearly every must-have is shown in the profile, with concrete examples.",
                "Most must-haves covered; one or two gaps that are quick to close.",
                "About half covered; noticeable gaps the application must address.",
                "A few covered; major gaps in the core of the role.",
                "Little overlap.",
            ],
        },
        {
            "key": "seniority", "short": "Lvl", "label": "Seniority",
            "description": "Level compared with your current or last role; one step up is best.",
            "notes": "",
            "levels": [
                "One step up from your last role.",
                "Two or more steps up.",
                "Same level.",
                "Level unclear or mixed signals.",
                "Below your level.",
            ],
        },
        {
            "key": "salary", "short": "Pay", "label": "Salary",
            "description": "Estimated pay against your target. Set your own bands.",
            "notes": "Say whether the bands are base salary or the full package, and in which "
                     "currency. If the posting gives no figure, estimate from the role, level, "
                     "company and city, and mark the estimate \"(est.)\" in --salary-estimate.",
            "levels": [
                "Well above your target",
                "At or above your target",
                "Just under your target",
                "Noticeably under your target",
                "Far below your target",
            ],
        },
    ],
}


def rubric_path() -> Path:
    return Path(os.environ.get("JSB_RUBRIC_PATH", "profile/rubric.json"))


def load_rubric(path: Path | None = None) -> dict:
    """Read the rubric; fall back to the built-in default if the file is missing."""
    path = path or rubric_path()
    if not path.exists():
        return copy.deepcopy(DEFAULT_RUBRIC)
    data = json.loads(path.read_text())
    for key, _ in RULE_LISTS:
        data.setdefault(key, [])
    data.setdefault("criteria", [])
    data.setdefault("rationale_guide", "")
    return data


def save_rubric(rubric: dict, path: Path | None = None) -> None:
    path = path or rubric_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rubric, indent=2, ensure_ascii=False) + "\n")


def criteria_labels(rubric: dict) -> list[tuple[str, str, str]]:
    """(key, short label, full label) for each criterion, in display order."""
    return [(c["key"], c["short"], c["label"]) for c in rubric["criteria"]]


def add_rule(rubric: dict, list_key: str, title: str, detail: str = "") -> None:
    if list_key not in dict(RULE_LISTS):
        raise ValueError(f"unknown rule list {list_key!r}")
    title = title.strip()
    if not title:
        raise ValueError("a rule needs a title")
    rubric[list_key].append({"title": title, "detail": detail.strip()})


def update_rule(rubric: dict, list_key: str, index: int, title: str, detail: str = "") -> None:
    if list_key not in dict(RULE_LISTS):
        raise ValueError(f"unknown rule list {list_key!r}")
    if not 0 <= index < len(rubric[list_key]):
        raise ValueError("no such rule")
    title = title.strip()
    if not title:
        raise ValueError("a rule needs a title")
    rubric[list_key][index] = {"title": title, "detail": detail.strip()}


def remove_rule(rubric: dict, list_key: str, index: int) -> None:
    if list_key not in dict(RULE_LISTS):
        raise ValueError(f"unknown rule list {list_key!r}")
    if not 0 <= index < len(rubric[list_key]):
        raise ValueError("no such rule")
    del rubric[list_key][index]


def add_criterion(
    rubric: dict, key: str, label: str, short: str, description: str,
    levels: list[str], notes: str = "",
) -> None:
    key = key.strip().lower()
    if not KEY_RE.match(key) or key in _RESERVED_KEYS:
        raise ValueError(
            "key must start with a letter and use only lowercase letters, digits and _ "
            "(max 24 characters)"
        )
    if any(c["key"] == key for c in rubric["criteria"]):
        raise ValueError(f"a criterion with key {key!r} already exists")
    rubric["criteria"].append(_criterion(key, label, short, description, levels, notes))


def _criterion(
    key: str, label: str, short: str, description: str, levels: list[str], notes: str,
) -> dict:
    if not label.strip():
        raise ValueError("a criterion needs a name")
    levels = [level.strip() for level in levels]
    if len(levels) != 5 or not all(levels):
        raise ValueError("describe what each score from 5 down to 1 means")
    return {
        "key": key,
        "short": (short.strip() or label.strip())[:4],
        "label": label.strip(),
        "description": description.strip(),
        "notes": notes.strip(),
        "levels": levels,
    }


def update_criterion(
    rubric: dict, key: str, label: str, short: str, description: str,
    levels: list[str], notes: str = "",
) -> None:
    """Change everything but the key (scores are stored against the key)."""
    for i, c in enumerate(rubric["criteria"]):
        if c["key"] == key:
            rubric["criteria"][i] = _criterion(key, label, short, description, levels, notes)
            return
    raise ValueError(f"no criterion {key!r}")


def remove_criterion(rubric: dict, key: str) -> None:
    before = len(rubric["criteria"])
    rubric["criteria"] = [c for c in rubric["criteria"] if c["key"] != key]
    if len(rubric["criteria"]) == before:
        raise ValueError(f"no criterion {key!r}")


def to_markdown(rubric: dict) -> str:
    """The rubric as instructions for whoever does the scoring."""
    criteria = rubric["criteria"]
    flags = " ".join(f"--{c['key']} N" for c in criteria)
    out = [
        "# Scoring Rubric",
        "",
        "Every posting gets one bucket and a 1-5 score for each criterion, recorded in a "
        "single call:",
        "",
        "```",
        f"app.cli score <job_id> <match|stretch|no_fit> {flags} \\",
        "  --salary-estimate '<e.g. $170k-$190k base (est.)>' '<rationale>'",
        "```",
        "",
        "Score the criteria for every job, including no_fit ones. For the bucket, apply the "
        "steps in order and stop at the first one that decides it.",
        "",
    ]
    steps = [
        ("1. Deal-breakers → `no_fit`",
         "Any one of these makes a job `no_fit`, however good the rest looks:",
         rubric["deal_breakers"]),
        ("2. `match`: one of the target role families, at the right level",
         "A job is a `match` only if it passed step 1 **and** is one of:",
         rubric["match_families"]),
        ("3. Otherwise → `stretch`",
         "Anything that passed step 1 but isn't a target role family, including:",
         rubric["stretch_examples"]),
    ]
    for heading, intro, rules in steps:
        out += [f"## {heading}", "", intro, ""]
        for rule in rules:
            detail = f": {rule['detail']}" if rule.get("detail") else ""
            out.append(f"- **{rule['title']}**{detail}")
        out.append("")
    if rubric.get("rationale_guide"):
        out += ["## Writing the rationale", "", rubric["rationale_guide"], ""]
    out += [
        f"## Criteria scores (1 to 5 each, total out of {5 * len(criteria)})",
        "",
        "Higher is always better for the candidate. Score from the posting; where it is "
        "silent, use the most likely reading and say so in the rationale.",
        "",
    ]
    for c in criteria:
        out += [f"### {c['label']} (`--{c['key']}`)", ""]
        if c.get("description"):
            out += [c["description"], ""]
        if c.get("notes"):
            out += [c["notes"], ""]
        out += ["| Score | Meaning |", "|---|---|"]
        for score, meaning in zip(range(5, 0, -1), c["levels"]):
            out.append(f"| {score} | {meaning} |")
        out.append("")
    return "\n".join(out)
