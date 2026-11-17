"""Edit profile/profile.md one '## ' section at a time.

Edits splice only the section being changed, so the rest of the file keeps
its exact formatting (and git diffs stay small). Each edit carries the
version (hash) of the file the user started from; if the file has changed
since (e.g. Claude updated it), the edit is refused instead of overwriting.
"""
import hashlib
import os
from pathlib import Path


class ProfileConflict(Exception):
    """The file changed since the user loaded it."""


def profile_path() -> Path:
    return Path(os.environ.get("JSB_PROFILE_PATH", "profile/profile.md"))


def read(path: Path) -> str:
    return path.read_text() if path.exists() else ""


def version(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _section_starts(lines: list[str]) -> list[int]:
    """Line numbers of '## ' headings, ignoring any inside ``` fences."""
    starts, fenced = [], False
    for i, line in enumerate(lines):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and line.startswith("## "):
            starts.append(i)
    return starts


def sections(text: str) -> list[dict]:
    """[{index, title, body}] for each '## ' section, in file order."""
    lines = text.splitlines()
    starts = _section_starts(lines)
    out = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        out.append({
            "index": n,
            "title": lines[start][3:].strip(),
            "body": "\n".join(lines[start + 1:end]).strip("\n"),
        })
    return out


def _check(title: str) -> str:
    title = " ".join(title.split())
    if not title:
        raise ValueError("a section needs a title")
    return title


def _block(title: str, body: str) -> list[str]:
    body = body.replace("\r\n", "\n").strip("\n")
    return [f"## {title}", ""] + (body.splitlines() + [""] if body else [])


def _write(path: Path, base_version: str, new_lines: list[str]) -> str:
    """Write if the file is still at base_version; return the new text."""
    if version(read(path)) != base_version:
        raise ProfileConflict()
    text = "\n".join(new_lines).rstrip("\n") + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text


def update_section(path: Path, base_version: str, index: int, title: str, body: str) -> str:
    title = _check(title)
    lines = read(path).splitlines()
    starts = _section_starts(lines)
    if not 0 <= index < len(starts):
        raise ProfileConflict()
    end = starts[index + 1] if index + 1 < len(starts) else len(lines)
    return _write(path, base_version, lines[:starts[index]] + _block(title, body) + lines[end:])


def delete_section(path: Path, base_version: str, index: int) -> str:
    lines = read(path).splitlines()
    starts = _section_starts(lines)
    if not 0 <= index < len(starts):
        raise ProfileConflict()
    end = starts[index + 1] if index + 1 < len(starts) else len(lines)
    return _write(path, base_version, lines[:starts[index]] + lines[end:])


def add_section(path: Path, base_version: str, title: str, body: str) -> str:
    """Append a section, keeping 'Scoring Rubric' (the rubric pointer) last."""
    title = _check(title)
    lines = read(path).splitlines()
    rubric = [i for i, s in zip(_section_starts(lines), sections("\n".join(lines)))
              if s["title"].lower() == "scoring rubric"]
    at = rubric[0] if rubric else len(lines)
    before = lines[:at]
    if before and before[-1].strip():
        before.append("")
    return _write(path, base_version, before + _block(title, body) + lines[at:])


def replace_all(path: Path, base_version: str, text: str) -> str:
    return _write(path, base_version, text.replace("\r\n", "\n").splitlines())
