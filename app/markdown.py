"""A small, safe markdown-to-HTML renderer for profile.md.

Covers what the profile uses: headings, paragraphs, bullet and numbered
lists (with wrapped lines), tables, fenced code, bold, italics, inline code
and links. All text is HTML-escaped first, so the output is safe to mark |safe.
"""
import html
import re

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BARE_URL = re.compile(r"(?<![\"'>=])\((https?://[^)\s]+)\)")
_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<![\w*])_(.+?)_(?![\w*])")


def inline(text: str) -> str:
    text = html.escape(text, quote=False)
    text = _CODE.sub(r"<code>\1</code>", text)
    text = _LINK.sub(r'<a href="\2" target="_blank" rel="noopener">\1</a>', text)
    text = _BARE_URL.sub(r'(<a href="\1" target="_blank" rel="noopener">\1</a>)', text)
    text = _BOLD.sub(r"<strong>\1</strong>", text)
    text = _ITALIC.sub(r"<em>\1</em>", text)
    return text


def render(md: str) -> str:
    out: list[str] = []
    lines = md.splitlines()
    i = 0
    para: list[str] = []

    def flush_para() -> None:
        if para:
            out.append(f"<p>{inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            flush_para()
            i += 1
        elif stripped.startswith("```"):
            flush_para()
            i += 1
            code = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
        elif m := re.match(r"^(#{1,6})\s+(.*)$", stripped):
            flush_para()
            level = len(m.group(1))
            out.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            i += 1
        elif stripped.startswith("|"):
            flush_para()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            body = [r for r in rows[1:] if not all(re.fullmatch(r":?-+:?", c) for c in r)]
            head = "".join(f"<th>{inline(c)}</th>" for c in rows[0])
            trs = "".join(
                "<tr>" + "".join(f"<td>{inline(c)}</td>" for c in r) + "</tr>" for r in body
            )
            out.append(f"<table><thead><tr>{head}</tr></thead><tbody>{trs}</tbody></table>")
        elif re.match(r"^([-*]|\d+\.)\s+", stripped):
            flush_para()
            ordered = bool(re.match(r"^\d+\.", stripped))
            items: list[str] = []
            while i < len(lines):
                s = lines[i].strip()
                if m := re.match(r"^([-*]|\d+\.)\s+(.*)$", s):
                    items.append(m.group(2))
                elif s and lines[i].startswith((" ", "\t")) and items:
                    items[-1] += " " + s  # wrapped continuation line
                else:
                    break
                i += 1
            tag = "ol" if ordered else "ul"
            out.append(f"<{tag}>" + "".join(f"<li>{inline(t)}</li>" for t in items) + f"</{tag}>")
        else:
            para.append(stripped)
            i += 1
    flush_para()
    return "\n".join(out)


def split_sections(md: str) -> tuple[str, list[dict]]:
    """Split on '## ' headings: (title from '# ', [{title, slug, body}])."""
    title = ""
    sections: list[dict] = []
    preamble: list[str] = []
    current = None
    for line in md.splitlines():
        if line.startswith("# ") and not title:
            title = line[2:].strip()
        elif line.startswith("## "):
            heading = line[3:].strip()
            current = {
                "title": heading,
                "slug": re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-"),
                "lines": [],
            }
            sections.append(current)
        elif current is None:
            preamble.append(line)
        else:
            current["lines"].append(line)
    for s in sections:
        s["body"] = "\n".join(s.pop("lines")).strip()
    return title, sections
