import html
import re


def html_to_text(raw_html: str) -> str:
    """Strip HTML tags down to plain text. Good enough for a job posting body."""
    # Some boards double-encode entities (e.g. "&amp;nbsp;"); unescape twice.
    text = html.unescape(html.unescape(raw_html))
    text = re.sub(r"<[^>]+>", "\n", text)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)
