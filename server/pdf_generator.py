import os
import re
import base64
import markdown
from jinja2 import Environment, FileSystemLoader
from weasyprint import HTML
from weasyprint.text.fonts import FontConfiguration
from latex2mathml.converter import convert

STATIC_DIR    = os.path.join(os.path.dirname(__file__), "static")
TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")

CONTEST_NAME  = os.environ.get("CONTEST_NAME",  "Contest")
CONTEST_DATES = os.environ.get("CONTEST_DATES", "")
SECTION_LANG  = os.environ.get("SECTION_LANG",  "th")

_LABELS = {
    "th": {
        "statement":   "โจทย์",
        "input":       "ข้อมูลนำเข้า",
        "output":      "ข้อมูลส่งออก",
        "constraints": "การให้คะแนน",
        "examples":    "ตัวอย่างข้อมูลนำเข้าและข้อมูลส่งออก",
        "notes":       "คำอธิบาย",
    },
    "en": {
        "statement":   "Problem Statement",
        "input":       "Input",
        "output":      "Output",
        "constraints": "Constraints",
        "examples":    "Sample Input/Output",
        "notes":       "Notes",
    },
}

_jinja_env   = Environment(loader=FileSystemLoader(TEMPLATES_DIR), autoescape=False)
_font_config = FontConfiguration()


def _detect_mime(data: bytes):
    if data[:4] == b'\x89PNG':
        return "image/png"
    if data[:2] == b'\xff\xd8':
        return "image/jpeg"
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "image/webp"
    if data[:4] == b'GIF8':
        return "image/gif"
    return None


def _render_math(html: str) -> str:
    """Convert $$...$$ (display) and $...$ (inline) LaTeX to MathML."""
    # Process display math first to avoid double-matching inner $
    html = re.sub(
        r'\$\$(.+?)\$\$',
        lambda m: convert(m.group(1), display="block"),
        html,
        flags=re.DOTALL,
    )
    html = re.sub(
        r'\$(.+?)\$',
        lambda m: convert(m.group(1), display="inline"),
        html,
    )
    return html


def _embed_images(html: str, images: dict) -> str:
    """Replace notion-img-* placeholder src values with base64 data URIs."""
    for placeholder, img_bytes in images.items():
        mime = _detect_mime(img_bytes)
        if mime is None:
            continue
        b64      = base64.b64encode(img_bytes).decode()
        data_uri = f"data:{mime};base64,{b64}"
        html     = html.replace(f'src="{placeholder}"', f'src="{data_uri}"')
    return html


def _markdown_to_html(text: str) -> str:
    return markdown.markdown(
        text,
        extensions=["extra", "nl2br", "sane_lists"],
    )


def generate_pdf(problem: dict) -> bytes:
    """Generate a PDF from a fully-assembled problem dict and return bytes."""
    sections_md = problem.get("sections", {})
    images      = problem.get("images",   {})

    sections_html = {}
    for key, md_text in sections_md.items():
        if not md_text:
            sections_html[key] = ""
            continue
        html = _markdown_to_html(md_text)
        html = _render_math(html)
        html = _embed_images(html, images)
        sections_html[key] = html

    labels   = _LABELS.get(SECTION_LANG, _LABELS["th"])
    template = _jinja_env.get_template("problem.html")

    html_str = template.render(
        title         = problem.get("title_full", ""),
        letter        = problem.get("letter",     ""),
        time_limit    = problem.get("time_limit",    "1 second"),
        memory_limit  = problem.get("memory_limit",  "256 MB"),
        contest_name  = CONTEST_NAME,
        contest_dates = CONTEST_DATES,
        sections      = sections_html,
        labels        = labels,
        static_dir    = STATIC_DIR,
    )

    pdf_bytes = HTML(string=html_str, base_url=STATIC_DIR).write_pdf(
        font_config=_font_config,
    )
    return pdf_bytes
