import os
import re
import base64
import xml.etree.ElementTree as ET
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


def _extract_math(text: str) -> tuple:
    """Replace $$...$$ and $...$ with placeholders BEFORE markdown processing.

    Markdown mangles LaTeX: underscores become <em>, asterisks become <strong>,
    so math must be pulled out first and restored after markdown runs.

    Returns (text_with_placeholders, {placeholder: mathml_string}).
    """
    placeholders = {}
    counter = [0]

    def _placeholder(mathml: str) -> str:
        key = f"MATHPLACEHOLDER{counter[0]}X"
        counter[0] += 1
        placeholders[key] = mathml
        return key

    # Display math first to avoid matching the inner $ of $$...$$
    text = re.sub(
        r'\$\$(.+?)\$\$',
        lambda m: _placeholder(convert(m.group(1), display="block")),
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'\$(.+?)\$',
        lambda m: _placeholder(convert(m.group(1), display="inline")),
        text,
    )
    return text, placeholders


def _restore_math(html: str, placeholders: dict) -> str:
    for key, mathml in placeholders.items():
        html = html.replace(key, mathml)
    return html


def _mathml_to_html(mathml: str) -> str:
    """Convert a MathML string to HTML using <sub>/<sup> for WeasyPrint.

    WeasyPrint's native MathML rendering of <msub>/<msup> is unreliable —
    children render inline at the same size/baseline.  Replacing them with
    HTML <sub>/<sup> (which WeasyPrint handles correctly) fixes this.
    """
    def _tag(elem):
        t = elem.tag
        return t.split('}', 1)[1] if '}' in t else t

    def _conv(elem):
        tag  = _tag(elem)
        text = elem.text or ''
        kids = list(elem)

        def ch():
            return ''.join(_conv(c) for c in kids)

        if tag == 'math':
            display = elem.get('display', 'inline')
            cls = 'math-block' if display == 'block' else 'math-inline'
            return f'<span class="{cls}">{ch()}</span>'
        if tag == 'mrow':
            return ch()
        if tag == 'mi':
            return f'<span class="math-mi">{text}</span>'
        if tag == 'mn':
            return f'<span class="math-mn">{text}</span>'
        if tag == 'mo':
            return f'<span class="math-mo">{text}{ch()}</span>'
        if tag == 'mtext':
            return f'<span class="math-text">{text}</span>'
        if tag == 'mspace':
            w = elem.get('width', '0.22em')
            return f'<span style="display:inline-block;width:{w}"></span>'
        if tag in ('mstyle', 'mpadded', 'mphantom', 'merror'):
            return ch()
        if tag == 'semantics' and kids:
            return _conv(kids[0])

        if tag == 'msub' and len(kids) == 2:
            return f'{_conv(kids[0])}<sub class="math-sub">{_conv(kids[1])}</sub>'
        if tag == 'msup' and len(kids) == 2:
            return f'{_conv(kids[0])}<sup class="math-sup">{_conv(kids[1])}</sup>'
        if tag == 'msubsup' and len(kids) == 3:
            return (f'{_conv(kids[0])}'
                    f'<sub class="math-sub">{_conv(kids[1])}</sub>'
                    f'<sup class="math-sup">{_conv(kids[2])}</sup>')
        if tag == 'munder' and len(kids) == 2:
            return f'{_conv(kids[0])}<sub class="math-sub">{_conv(kids[1])}</sub>'
        if tag == 'mover' and len(kids) == 2:
            return f'{_conv(kids[0])}<sup class="math-sup">{_conv(kids[1])}</sup>'
        if tag == 'munderover' and len(kids) == 3:
            return (f'{_conv(kids[0])}'
                    f'<sub class="math-sub">{_conv(kids[1])}</sub>'
                    f'<sup class="math-sup">{_conv(kids[2])}</sup>')

        if tag == 'mfrac' and len(kids) == 2:
            return (f'<span class="math-frac">'
                    f'<span class="math-num">{_conv(kids[0])}</span>'
                    f'<span class="math-den">{_conv(kids[1])}</span>'
                    f'</span>')
        if tag == 'msqrt':
            return f'√<span class="math-sqrt">{ch()}</span>'
        if tag == 'mroot' and len(kids) == 2:
            return f'<sup class="math-sup math-root-idx">{_conv(kids[1])}</sup>√{_conv(kids[0])}'

        # Fallback: pass text content + children through
        return text + ch()

    try:
        root = ET.fromstring(mathml)
        return _conv(root)
    except ET.ParseError:
        return mathml  # leave original MathML on parse error


def _extract_math_pdf(text: str) -> tuple:
    """Like _extract_math but placeholders hold HTML (not MathML) for WeasyPrint."""
    placeholders = {}
    counter = [0]

    def _placeholder(html: str) -> str:
        key = f"MATHPLACEHOLDER{counter[0]}X"
        counter[0] += 1
        placeholders[key] = html
        return key

    text = re.sub(
        r'\$\$(.+?)\$\$',
        lambda m: _placeholder(_mathml_to_html(convert(m.group(1), display="block"))),
        text,
        flags=re.DOTALL,
    )
    text = re.sub(
        r'\$(.+?)\$',
        lambda m: _placeholder(_mathml_to_html(convert(m.group(1), display="inline"))),
        text,
    )
    return text, placeholders


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
        md_text, math_placeholders = _extract_math_pdf(md_text)
        html = _markdown_to_html(md_text)
        html = _restore_math(html, math_placeholders)
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


def generate_html(problem: dict) -> str:
    """Return the rendered HTML string (same pipeline as generate_pdf, without the PDF step)."""
    sections_md = problem.get("sections", {})
    images      = problem.get("images",   {})

    sections_html = {}
    for key, md_text in sections_md.items():
        if not md_text:
            sections_html[key] = ""
            continue
        md_text, math_placeholders = _extract_math(md_text)
        html = _markdown_to_html(md_text)
        html = _restore_math(html, math_placeholders)
        html = _embed_images(html, images)
        sections_html[key] = html

    labels   = _LABELS.get(SECTION_LANG, _LABELS["th"])
    template = _jinja_env.get_template("problem.html")

    return template.render(
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
