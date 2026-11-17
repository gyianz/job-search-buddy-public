import re
import sys

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, ListFlowable, ListItem

def inline(text):
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"\*(.+?)\*", r"<i>\1</i>", text)
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<link href="\2" color="blue">\1</link>', text)
    return text

def md_to_pdf(md_path, pdf_path, title_size=20):
    with open(md_path) as f:
        lines = f.read().splitlines()

    styles = getSampleStyleSheet()
    h1 = ParagraphStyle("H1", parent=styles["Title"], fontSize=title_size, spaceAfter=4, alignment=0)
    h2 = ParagraphStyle("H2", parent=styles["Heading2"], fontSize=12, spaceBefore=10, spaceAfter=4, textColor="#1a1a1a")
    h3 = ParagraphStyle("H3", parent=styles["Heading3"], fontSize=10.5, spaceBefore=8, spaceAfter=2)
    body = ParagraphStyle("Body", parent=styles["Normal"], fontSize=9.5, leading=13, spaceAfter=4)
    bullet = ParagraphStyle("Bullet", parent=body, leftIndent=14)
    italic_note = ParagraphStyle("ItalicNote", parent=body, fontSize=8.5, textColor="#555555")

    story = []
    bullets = []
    excluding = False

    def flush_bullets():
        nonlocal bullets
        if bullets:
            story.append(ListFlowable(
                [ListItem(Paragraph(inline(b), bullet), leftIndent=10) for b in bullets],
                bulletType="bullet", start="circle", leftIndent=14,
            ))
            bullets = []

    for raw in lines:
        line = raw.rstrip()
        if line.strip() == "<!-- pdf:exclude-start -->":
            excluding = True
            continue
        if line.strip() == "<!-- pdf:exclude-end -->":
            excluding = False
            continue
        if excluding:
            continue
        if not line.strip():
            flush_bullets()
            story.append(Spacer(1, 4))
            continue
        if line.startswith("# "):
            flush_bullets()
            story.append(Paragraph(inline(line[2:]), h1))
        elif line.startswith("## "):
            flush_bullets()
            story.append(Paragraph(inline(line[3:]), h2))
        elif line.startswith("### "):
            flush_bullets()
            story.append(Paragraph(inline(line[4:]), h3))
        elif line.startswith("- "):
            bullets.append(line[2:])
        elif line.strip() == "---":
            flush_bullets()
            story.append(Spacer(1, 6))
        elif line.startswith("*") and line.endswith("*") and not line.startswith("**"):
            flush_bullets()
            story.append(Paragraph(inline(line), italic_note))
        else:
            flush_bullets()
            story.append(Paragraph(inline(line), body))

    flush_bullets()

    doc = SimpleDocTemplate(
        pdf_path, pagesize=letter,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        leftMargin=0.7 * inch, rightMargin=0.7 * inch,
    )
    doc.build(story)
    print(f"wrote {pdf_path}")

if __name__ == "__main__":
    md_path, pdf_path = sys.argv[1], sys.argv[2]
    md_to_pdf(md_path, pdf_path)
