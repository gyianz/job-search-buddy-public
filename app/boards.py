"""The job boards `fetch` pulls from: entries in seed_companies.json."""
import json
import os
from pathlib import Path

from app.ats.fetch import FETCHERS

# What the token is, per platform: (display name, board URL with {token}).
PLATFORMS = {
    "greenhouse": ("Greenhouse", "https://boards.greenhouse.io/{token}"),
    "lever": ("Lever", "https://jobs.lever.co/{token}"),
    "ashby": ("Ashby", "https://jobs.ashbyhq.com/{token}"),
    "smartrecruiters": ("SmartRecruiters", "https://jobs.smartrecruiters.com/{token}"),
    "workable": ("Workable", "https://apply.workable.com/{token}"),
}
assert set(PLATFORMS) == set(FETCHERS)


def seed_path() -> Path:
    return Path(os.environ.get("JSB_SEED_PATH", "seed_companies.json"))


def load_boards(path: Path | None = None) -> list[dict]:
    path = path or seed_path()
    if not path.exists():
        return []
    return json.loads(path.read_text())


def save_boards(boards: list[dict], path: Path | None = None) -> None:
    path = path or seed_path()
    path.write_text(json.dumps(boards, indent=2, ensure_ascii=False) + "\n")


def board_url(entry: dict) -> str | None:
    platform = PLATFORMS.get(entry.get("platform", ""))
    return platform[1].format(token=entry.get("token", "")) if platform else None


def _keywords(raw: str) -> list[str]:
    # Keep inner spaces ("ml " is a deliberate keyword), drop empty entries.
    return [k for k in (part.lstrip() for part in raw.split(",")) if k.strip()]


def add_board(
    boards: list[dict], name: str, platform: str, token: str,
    title_keywords: str = "", location_keywords: str = "",
) -> dict:
    name, token = name.strip(), token.strip().strip("/")
    if not name or not token:
        raise ValueError("company name and board token are both required")
    if platform not in PLATFORMS:
        raise ValueError(f"unknown platform {platform!r}")
    if any(b.get("platform") == platform and b.get("token") == token for b in boards):
        raise ValueError(f"{PLATFORMS[platform][0]} board {token!r} is already connected")
    entry = {"name": name, "platform": platform, "token": token}
    if kws := _keywords(title_keywords):
        entry["title_keywords"] = kws
    if kws := _keywords(location_keywords):
        entry["location_keywords"] = kws
    boards.append(entry)
    return entry


def remove_board(boards: list[dict], platform: str, token: str) -> dict:
    for i, b in enumerate(boards):
        if b.get("platform") == platform and b.get("token") == token:
            return boards.pop(i)
    raise ValueError("no such board")
