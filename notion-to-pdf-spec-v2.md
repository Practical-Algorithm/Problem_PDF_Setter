# Contest Problem PDF Generator — Technical Specification

**Version:** 2.0  
**Application:** `notion-to-pdf`  
**Purpose:** Automatically generate per-problem contest PDFs from a Notion database, served via a self-hosted web application on a homelab.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Problem Statement & Motivation](#2-problem-statement--motivation)
3. [Architecture](#3-architecture)
4. [Technology Stack](#4-technology-stack)
5. [Project Structure](#5-project-structure)
6. [Component Deep Dives](#6-component-deep-dives)
   - 6.1 [Flask Web Server (`app.py`)](#61-flask-web-server-apppy)
   - 6.2 [Notion Client Wrapper (`notion_client_wrapper.py`)](#62-notion-client-wrapper-notion_client_wrapperpy)
   - 6.3 [PDF Generator (`pdf_generator.py`)](#63-pdf-generator-pdf_generatorpy)
   - 6.4 [HTML/CSS Problem Template (`templates/problem.html`)](#64-htmlcss-problem-template-templatesproblemhtml)
   - 6.5 [Web UI (`templates/index.html`)](#65-web-ui-templatesindexhtml)
7. [Data Flow](#7-data-flow)
8. [Notion Database Schema](#8-notion-database-schema)
9. [Notion Page Content Convention](#9-notion-page-content-convention)
10. [Configuration Reference](#10-configuration-reference)
11. [API Reference](#11-api-reference)
12. [Docker & Deployment](#12-docker--deployment)
13. [PDF Visual Design Specification](#13-pdf-visual-design-specification)
14. [Image Handling](#14-image-handling)
15. [Error Handling Strategy](#15-error-handling-strategy)
16. [Math Rendering](#16-math-rendering)
17. [Technology Primers](#17-technology-primers)
    - 17.1 [Python & pip](#171-python--pip)
    - 17.2 [Flask](#172-flask)
    - 17.3 [Notion API](#173-notion-api)
    - 17.4 [Markdown](#174-markdown)
    - 17.5 [Jinja2 Templating](#175-jinja2-templating)
    - 17.6 [WeasyPrint (HTML → PDF)](#176-weasyprint-html--pdf)
    - 17.7 [Docker & Docker Compose](#177-docker--docker-compose)
18. [Development Guide](#18-development-guide)
19. [Extending the Application](#19-extending-the-application)

---

## 1. System Overview

This application is a self-hosted web service that bridges **Notion** (used collaboratively by a contest organiser team to write problem statements) and **PDF output** (required for the actual contest). Team members visit a simple web page, select which problems to include, and immediately download correctly formatted PDFs — without sharing API credentials, without touching LaTeX, and without any manual formatting work.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         HOMELAB SERVER                              │
│                                                                     │
│  ┌────────────┐    ┌──────────────────┐    ┌─────────────────────┐ │
│  │            │    │                  │    │                     │ │
│  │  Flask     │───▶│  Notion Client   │───▶│  Notion API         │ │
│  │  Web App   │    │  Wrapper         │    │  (cloud)            │ │
│  │  :5000     │    │                  │    │                     │ │
│  │            │    └──────────────────┘    └─────────────────────┘ │
│  │            │                                                     │
│  │            │    ┌──────────────────┐    ┌─────────────────────┐ │
│  │            │───▶│  PDF Generator   │───▶│  WeasyPrint         │ │
│  │            │    │  (Jinja2 +       │    │  (HTML → PDF)       │ │
│  └────────────┘    │   Markdown +     │    │                     │ │
│        ▲           │   MathML)        │    └─────────────────────┘ │
│        │           └──────────────────┘                            │
└────────┼────────────────────────────────────────────────────────────┘
         │
    Browser (team members — internet-accessible, password protected)
```

---

## 2. Problem Statement & Motivation

### The Manual Process (Before)

1. Problem setters write problem statements in **Notion** collaboratively.
2. When ready, the organiser manually exports each page from Notion (as Markdown or HTML).
3. The exported content is pasted into **Overleaf** (an online LaTeX editor).
4. The organiser hand-tweaks LaTeX formatting — fixing headers, sample I/O table layout, fonts, page margins, etc.
5. The PDF is compiled and reviewed.
6. Any edit in Notion means repeating steps 2–5.

This process is slow, error-prone, and requires LaTeX knowledge.

### The Automated Process (After)

1. Problem setters write in Notion as before. No change to their workflow.
2. Any team member visits `https://<your-domain>` in a browser and logs in with the shared team password.
3. They select which problems to include using checkboxes, then click **"Download ZIP"**. A progress bar shows generation status per problem.
4. Individual PDFs can also be downloaded one at a time with **"⬇ PDF"**.

The Notion API key lives only on the server. No credentials are shared.

---

## 3. Architecture

### Architectural Pattern: Server-Side Rendering

This application follows a classic **server-side rendering** pattern. The server does all the heavy lifting:

- Authenticating requests (HTTP Basic Auth)
- Fetching data from Notion
- Parsing Markdown and converting LaTeX math to MathML
- Rendering HTML from a template
- Converting HTML to PDF

The browser renders a UI for listing problems, selecting a bundle, and triggering downloads.

### Concurrency & Deployment Model

The server runs with **Gunicorn** (not Flask's development server), with **2 workers** — sufficient for 1–3 concurrent users. PDF generation is CPU-bound and takes 1–5 seconds per request; multiple workers prevent one user's request from blocking others.

```dockerfile
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "120", "app:app"]
```

The `--timeout 120` flag accommodates the bundle endpoint, which can take 30–80 seconds for ~8 problems. `python app.py` must **never** be used in production — it runs Flask's single-threaded development server. See §18 for the correct local development workflow.

### Authentication

The app is publicly accessible over the internet. **HTTP Basic Auth** via `flask-httpauth` protects all routes. The password is set via the `APP_PASSWORD` environment variable (see §10).

```python
from flask_httpauth import HTTPBasicAuth
auth = HTTPBasicAuth()

USERS = {"team": os.environ.get("APP_PASSWORD", "")}

@auth.verify_password
def verify(username, password):
    stored = USERS.get(username)
    if not stored:
        return False
    return stored == password
```

> **Security requirement:** HTTP Basic Auth transmits credentials in base64, which is trivially decoded over plain HTTP. The container **must** sit behind a TLS-terminating reverse proxy for any internet-facing deployment. See §12 for the Caddy setup.

### Request Lifecycle

```
Browser                        Flask Server                   Notion API
   │                                │                              │
   │  GET /                         │                              │
   │──────────────────────────────▶│                              │
   │  ◀── index.html (+ auth) ──────│                              │
   │                                │                              │
   │  GET /api/problems             │                              │
   │──────────────────────────────▶│                              │
   │                                │  databases.query(db_id)     │
   │                                │────────────────────────────▶│
   │                                │  ◀── list of pages ─────────│
   │  ◀── JSON array of problems ───│                              │
   │                                │                              │
   │  GET /api/problems/<id>/pdf    │                              │
   │──────────────────────────────▶│                              │
   │                                │  pages.retrieve(page_id)    │
   │                                │────────────────────────────▶│
   │                                │  blocks.children.list(...)  │
   │                                │────────────────────────────▶│
   │                                │  ◀── page content ──────────│
   │                                │                              │
   │                                │  [parse blocks → Markdown]   │
   │                                │  [Markdown → HTML]           │
   │                                │  [LaTeX math → MathML]       │
   │                                │  [Jinja2 render template]    │
   │                                │  [WeasyPrint → PDF bytes]    │
   │                                │                              │
   │  ◀── PDF file download ────────│                              │
```

---

## 4. Technology Stack

| Layer | Technology | Why chosen |
|---|---|---|
| Web framework | **Flask** (Python) | Lightweight, minimal boilerplate, easy to understand |
| WSGI server | **Gunicorn** | Production-grade multi-worker server; required for concurrent users |
| Authentication | **flask-httpauth** | Simple HTTP Basic Auth; integrates cleanly with Flask routes |
| Notion integration | **notion-client** (official Python SDK) | Handles authentication, pagination, and rate limits |
| Markdown parsing | **python-markdown** | Converts Markdown text to HTML; extensible |
| Math rendering | **latex2mathml** | Server-side LaTeX → MathML conversion; no JavaScript runtime needed |
| HTML templating | **Jinja2** | Industry-standard Python templating; ships with Flask |
| HTML → PDF | **WeasyPrint** | Pure Python, no headless browser required, excellent CSS support including paged media; renders MathML natively |
| Font | **Bai Jamjuree** (Google Fonts) | Covers Thai and Latin scripts in a single typeface |
| Image downloading | **requests** | Standard HTTP library for fetching Notion-hosted images |
| Containerisation | **Docker + Docker Compose** | Ensures consistent environment; easy homelab deployment |
| Configuration | **python-dotenv + environment variables** | Separates secrets from code |
| Reverse proxy / TLS | **Caddy** | Automatic Let's Encrypt certificates; simple config |

---

## 5. Project Structure

```
notion-to-pdf/
│
├── .env.example               ← Template for environment variables (copy → .env)
├── Caddyfile                  ← Reverse proxy + TLS config (internet-facing deployments)
├── Dockerfile                 ← Container image definition
├── docker-compose.yml         ← Multi-container orchestration
│
└── server/
    ├── app.py                 ← Flask application: routes, auth, request handling
    ├── notion_client_wrapper.py  ← Notion API: fetch DB, parse blocks, download images
    ├── pdf_generator.py       ← Orchestrate Markdown→MathML→HTML→PDF pipeline
    ├── requirements.txt       ← Python package dependencies
    │
    ├── templates/
    │   ├── index.html         ← Web UI (the page team members see)
    │   └── problem.html       ← PDF layout template (HTML + CSS)
    │
    └── static/
        └── logo.png           ← Contest logo (supplied by organiser each year)
```

---

## 6. Component Deep Dives

### 6.1 Flask Web Server (`app.py`)

**Responsibility:** Receive HTTP requests, enforce authentication, coordinate the Notion client and PDF generator, and return responses (HTML pages, JSON, PDFs, ZIP archives, or SSE streams).

#### Routes Defined in `app.py`

**`GET /`**  
Serves the web UI. Requires auth. Uses `render_template("index.html")`.

**`GET /api/problems`**  
Returns a JSON array of all problems in the Notion database (filtered by `NOTION_FILTER_STATUS` if set). Requires auth. Each item contains: `id`, `title`, `letter`, `time_limit`, `memory_limit`, `difficulty`, `status`, `last_edited_time`.

Example response:
```json
[
  {
    "id": "abc123...",
    "title": "กลับบ้าน (Place To Call Home)",
    "letter": "A",
    "time_limit": "1 second",
    "memory_limit": "256 MB",
    "difficulty": "Medium",
    "status": "Ready",
    "last_edited_time": "2025-06-01T12:34:56.000Z"
  }
]
```

**`GET /api/problems/<page_id>/pdf`**  
The core single-problem endpoint. Given a Notion page ID:
1. Checks the in-memory cache keyed by `(page_id, last_edited_time)`. Returns cached bytes immediately on a hit.
2. On a miss: calls `notion.get_problem(page_id)`, then `generate_pdf(problem)`.
3. Returns the PDF as an attachment download.
4. Attaches any warnings to the `X-PDF-Warnings` response header.

**`DELETE /api/problems/<page_id>/cache`**  
Clears the cached PDF for a single problem. Returns `{"ok": true}`. Exposed in the UI as a **"↺ Refresh"** button on each problem card.

**`DELETE /api/problems/cache`**  
Clears the entire in-memory PDF cache. Returns `{"cleared": <count>}`. Exposed in the UI as a **"Clear All Cache"** button.

**`POST /api/problems/bundle/stream`**  
Accepts a JSON body `{"page_ids": ["abc123", ...]}` and opens a **Server-Sent Events** stream. Generates PDFs for the specified problems sequentially, emitting progress events. See §11 for the full SSE protocol.

**`GET /api/problems/bundle/download?token=<token>`**  
Exchanges a short-lived token (emitted by the SSE stream on completion) for the ZIP file download.

#### Error Handling Pattern

Every route wraps its body in `try/except`:

```python
try:
    result = do_something()
    return jsonify(result)
except Exception as e:
    app.logger.exception("Unhandled error in route")
    return jsonify({"error": str(e)}), 500
```

`app.logger.exception` logs the full traceback to stdout (visible via `docker compose logs -f`). The browser's JavaScript checks for error responses and adds them to the persistent warning panel.

#### Startup Validation

Before the server accepts any requests, it must validate the environment:

```python
def validate_startup():
    if not os.environ.get("APP_PASSWORD"):
        raise RuntimeError("APP_PASSWORD environment variable is not set. Refusing to start.")
    
    # Verify Notion database is reachable and has expected properties
    db = notion_client.client.databases.retrieve(NOTION_DATABASE_ID)
    existing = set(db["properties"].keys())
    required = {PROP_TITLE, PROP_LETTER, PROP_TIME, PROP_MEMORY}
    missing = required - existing
    if missing:
        raise RuntimeError(
            f"Notion database is missing expected properties: {missing}. "
            f"Check your NOTION_PROP_* environment variables."
        )
```

If validation fails, the server logs the error and exits with a non-zero status code. It does not silently start in a broken state.

---

### 6.2 Notion Client Wrapper (`notion_client_wrapper.py`)

**Responsibility:** All communication with the Notion API. Exposes two public methods: `list_problems()` and `get_problem(page_id)`.

#### Understanding the Notion Data Model

```
Database (one per contest)
  └── Page (one per problem)
        ├── Properties (structured fields: Title, Letter, Time Limit, ...)
        └── Content Blocks (the actual text: paragraphs, headings, code blocks, images, tables, ...)
```

#### Pagination

The Notion API returns at most 100 results per request. Both `list_problems()` and `_all_blocks()` use the cursor-based pagination loop:

```python
while True:
    response = self.client.databases.query(database_id=..., start_cursor=cursor)
    results.extend(response["results"])
    if not response.get("has_more"):
        break
    cursor = response["next_cursor"]
```

#### Rate Limit Handling

All Notion API calls must be wrapped with retry logic:

```python
import time

def _notion_call_with_retry(fn, *args, **kwargs):
    for attempt in range(4):  # 1 attempt + 3 retries
        try:
            return fn(*args, **kwargs)
        except APIResponseError as e:
            if e.status == 429 and attempt < 3:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue
            raise
```

#### Block Parsing: Section Detection

The parser reads all blocks in order and groups them into named sections. A **Heading 2** block marks the start of a new section. The heading text is matched against the following exact table:

| Heading 2 text in Notion | Maps to section | Match type |
|---|---|---|
| `ข้อมูลนำเข้า` | `input` | Exact Unicode (strip whitespace) |
| `ข้อมูลส่งออก` | `output` | Exact Unicode (strip whitespace) |
| `การให้คะแนน` | `constraints` | Exact Unicode (strip whitespace) |
| `Constraints` | `constraints` | Case-insensitive |
| `Sample Input/Output` | `examples` | Case-insensitive |

Everything before the first Heading 2 goes into `statement` automatically. There is no `statement` heading — it is always implicit.

**Any Heading 2 that does not appear in this table is an unrecognised section.** Its content is dropped from the PDF and a warning is emitted (see §15). There is no fuzzy matching and no fallback guessing.

> **Note for §9:** Problem setters must use these heading texts exactly. Thai headings must match character-for-character. The two English exceptions (`Constraints`, `Sample Input/Output`) are case-insensitive. No other variation is accepted.

#### Rich Text Annotations

| Annotation | Markdown output |
|---|---|
| bold | `**text**` |
| italic | `*text*` |
| bold + italic | `***text***` |
| code | `` `text` `` |

#### Block Type Mapping

| Notion block type | Converted to |
|---|---|
| `paragraph` | Plain paragraph text |
| `heading_3` | `### heading` |
| `bulleted_list_item` | `- item` |
| `numbered_list_item` | `1. item` |
| `code` | Fenced code block (` ```lang ... ``` `) |
| `quote` | `> text` |
| `callout` | `> **Note:** text` |
| `divider` | `---` |
| `table` | Markdown table with `\|` syntax |
| `image` | Downloaded and stored separately (see §14) |
| `heading_1`, `heading_2` | Section boundary marker (not output as text) |

#### Image Downloading

When an `image` block is encountered, `_fetch_image()` downloads the image bytes using `requests`. Notion images have two source types:

- **`file`**: Notion-hosted. URL is in `block["image"]["file"]["url"]`. This is a pre-signed AWS S3 URL that **expires in approximately 1 hour**. Images must be downloaded at PDF-generation time, not cached separately.
- **`external`**: Any public image URL. URL is in `block["image"]["external"]["url"]`.

A unique placeholder string (`uuid.uuid4().hex`) is generated and stored alongside the downloaded bytes in an `images` dict. The placeholder is injected into the Markdown:

```html
<img src="notion-img-a3f7c2..." alt="caption text">
```

The PDF generator later replaces these placeholders with base64-encoded data URIs (see §14).

#### Property Name Flexibility

All Notion property names are read from environment variables with sensible defaults:

```python
PROP_TITLE      = os.environ.get("NOTION_PROP_TITLE",      "Name")
PROP_LETTER     = os.environ.get("NOTION_PROP_LETTER",     "Problem Letter")
PROP_TIME       = os.environ.get("NOTION_PROP_TIME",       "Time Limit")
PROP_MEMORY     = os.environ.get("NOTION_PROP_MEMORY",     "Memory Limit")
PROP_DIFFICULTY = os.environ.get("NOTION_PROP_DIFFICULTY", "Difficulty")
PROP_STATUS     = os.environ.get("NOTION_PROP_STATUS",     "Status")
```

#### Title Parsing: Bilingual Titles

Problem titles in Notion follow the convention `ชื่อไทย (English Name)`. The wrapper must extract both parts:

```python
import re

def _parse_title(raw_title: str) -> dict:
    match = re.search(r'\(([^)]+)\)\s*$', raw_title.strip())
    if match:
        return {
            "title_full": raw_title.strip(),
            "title_en": match.group(1).strip(),
        }
    return {
        "title_full": raw_title.strip(),
        "title_en": raw_title.strip(),
    }
```

`title_full` is used for the PDF title and the UI display. `title_en` is used for ZIP filenames (see §11).

---

### 6.3 PDF Generator (`pdf_generator.py`)

**Responsibility:** Take a fully-assembled problem dict and return a PDF as `bytes`.

#### Pipeline

```
sections dict (Markdown strings)
         │
         ▼
    python-markdown
         │
         ▼
  sections dict (HTML strings)
         │
         ▼
  _render_math() — convert $...$ and $$...$$ to MathML
         │
         ▼
  _embed_images() — replace placeholders with base64 data URIs
         │
         ▼
  Jinja2 render problem.html template
         │
         ▼
  WeasyPrint HTML() → .write_pdf()
         │
         ▼
       bytes
```

#### Markdown to HTML

`markdown.markdown()` is called on each section's text. Extensions used:

- **`extra`**: Enables tables, fenced code blocks, and attribute syntax.
- **`nl2br`**: Converts single newlines to `<br>` tags.
- **`sane_lists`**: Fixes edge cases in list parsing.

#### Math Rendering

After Markdown→HTML conversion, `_render_math()` is applied to each section **before** sections are joined. It must not be applied inside fenced code blocks — extract and restore code block content around the call if necessary.

```python
import re
from latex2mathml.converter import convert

def _render_math(html: str) -> str:
    # Process display math ($$...$$) before inline ($...$)
    html = re.sub(
        r'\$\$(.+?)\$\$',
        lambda m: convert(m.group(1), display="block"),
        html, flags=re.DOTALL
    )
    html = re.sub(
        r'\$(.+?)\$',
        lambda m: convert(m.group(1), display="inline"),
        html
    )
    return html
```

WeasyPrint renders MathML natively via Pango/Cairo. No additional system dependencies are required.

#### Image Embedding

WeasyPrint renders HTML locally and cannot make network requests. Every image is converted to a **base64 data URI**:

```python
b64 = base64.b64encode(img_bytes).decode()
data_uri = f"data:{mime_type};base64,{b64}"
html = html.replace(f'src="{placeholder}"', f'src="{data_uri}"')
```

The MIME type is detected from the image's magic bytes (see §14).

#### WeasyPrint

```python
HTML(string=html_str, base_url=STATIC_DIR).write_pdf()
```

`base_url` tells WeasyPrint where to resolve relative file paths — how `logo.png` is found. `FontConfiguration()` is passed to enable custom font caching.

#### Contest Configuration

| Variable | Purpose | Default |
|---|---|---|
| `CONTEST_NAME` | Right side of page header | `"Contest"` |
| `CONTEST_DATES` | Below contest name in header | `""` |
| `SECTION_LANG` | Section heading language (`"th"` or `"en"`) | `"th"` |

---

### 6.4 HTML/CSS Problem Template (`templates/problem.html`)

**Responsibility:** Define the entire visual layout of the PDF. Edit this file to change how the PDF looks — no Python changes needed.

#### CSS Paged Media

```css
@page {
  size: A4;
  margin: 3.2cm 2.5cm 2.5cm 2.5cm;

  @top-left {
    content: element(page-header);
  }

  @bottom-right {
    content: counter(page);
    border-top: 1.5px solid #1a1a1a;
  }
}

#page-header {
  position: running(page-header);
}
```

#### Font Loading

```css
@import url('https://fonts.googleapis.com/css2?family=Bai+Jamjuree:...');
```

WeasyPrint fetches the font from Google Fonts on the first render and caches it. For offline deployments, see §19.

#### Jinja2 Variables in the Template

| Variable | Type | Description |
|---|---|---|
| `title` | string | Full bilingual problem title |
| `letter` | string | Problem letter ("A", "B", ...) |
| `time_limit` | string | e.g. "1 second" |
| `memory_limit` | string | e.g. "256 MB" |
| `contest_name` | string | From `CONTEST_NAME` env var |
| `contest_dates` | string | From `CONTEST_DATES` env var |
| `sections` | dict | Keys: `statement`, `input`, `output`, `constraints`, `examples`, `notes`; Values: HTML strings |
| `labels` | dict | Localised section heading strings |
| `static_dir` | string | Absolute path to `server/static/` |

---

### 6.5 Web UI (`templates/index.html`)

**Responsibility:** Present a clean, usable interface for team members to browse problems, select a bundle, and download PDFs.

This is a single-page application built with vanilla JavaScript (no frameworks), served by Flask.

#### Loading Flow

1. Browser loads `/` → Flask returns `index.html` (after auth).
2. Page's `<script>` calls `loadProblems()` immediately on load.
3. `loadProblems()` calls `fetch('/api/problems')`.
4. On success, `renderProblems()` builds HTML cards dynamically.
5. A search box filters the `allProblems` array client-side.

#### Problem Card

Each card shows:
- Problem title (bilingual) and letter badge
- Time limit and memory limit
- Difficulty badge
- **Checkbox** for bundle selection
- **"⬇ PDF"** button — downloads a single problem PDF
- **"↺ Refresh"** button — clears the cached PDF and forces re-fetch from Notion

#### Bundle Selection UI

- A **"Select All" / "Deselect All"** control above the problem list.
- A counter near the bundle button: **"Bundle: 5 / 8 selected"**.
- **"Download ZIP"** button — disabled (greyed out) when zero problems are selected.
- On page load, all problems default to **unselected**.
- Selection state is held in JavaScript memory and does not persist across page refreshes.

When the user clicks "Download ZIP":
1. The UI collects the `page_id` values of all checked problems.
2. It opens an SSE connection to `POST /api/problems/bundle/stream` with `{"page_ids": [...]}`.
3. A **progress bar** updates per problem: "Generating กลับบ้าน… 3 / 5".
4. On the `"done"` event, the UI automatically calls `GET /api/problems/bundle/download?token=<token>` to trigger the file download.

#### Warning & Error Panel

A persistent **collapsible panel** in the page header accumulates all warnings and errors from the current session. It is never auto-cleared — the user must dismiss entries manually. Warnings from `X-PDF-Warnings` headers and errors from failed API calls both appear here.

#### Global Cache Controls

A **"Clear All Cache"** button in the page header calls `DELETE /api/problems/cache` and resets the cached state for all problems.

---

## 7. Data Flow

### Full Data Flow: Single Problem PDF

```
1. Browser → GET /api/problems/<page_id>/pdf

2. app.py: check cache (page_id, last_edited_time)
   ├── Cache HIT → return cached PDF bytes immediately
   └── Cache MISS →

3. app.py: notion.get_problem(page_id)
   │
   ├── Notion API: pages.retrieve(page_id)
   │     └── Returns: {title, letter, time_limit, memory_limit, ...}
   │
   └── Notion API: blocks.children.list(page_id)  [paginated]
         └── Returns: list of block objects
               │
               ├── _parse_blocks() groups blocks into sections
               │     ├── "statement": ["paragraph text", ...]
               │     ├── "input":     ["paragraph text", ...]
               │     └── ...
               │
               └── _fetch_image() for each image block
                     └── requests.get(image_url) → bytes

4. problem dict assembled:
   {
     "title_full": "กลับบ้าน (Place To Call Home)",
     "title_en": "Place To Call Home",
     "letter": "A",
     "time_limit": "1 second",
     "sections": {"statement": "markdown...", "input": "markdown...", ...},
     "images": {"notion-img-abc123": b'\x89PNG...', ...},
     "warnings": []
   }

5. app.py: generate_pdf(problem)
   │
   ├── markdown.markdown(section_text) for each section → HTML strings
   │
   ├── _render_math(): $...$ and $$...$$ → MathML
   │
   ├── _embed_images(): replace img placeholders with base64 data URIs
   │
   ├── Jinja2: render problem.html with all variables → full HTML string
   │
   └── WeasyPrint: HTML(string=html).write_pdf() → bytes

6. Store in cache keyed by (page_id, last_edited_time)

7. Flask: send_file(BytesIO(pdf_bytes), as_attachment=True)
         + X-PDF-Warnings header → browser download
```

---

## 8. Notion Database Schema

The application expects a Notion database where each row represents one problem.

| Property Name (default) | Notion Type | Required | Description |
|---|---|---|---|
| `Name` | Title | ✅ Yes | Bilingual problem name: `ชื่อไทย (English Name)`. English part used for ZIP filenames. |
| `Problem Letter` | Rich text | No | Contest letter: "A", "B", "C", ... Used for sorting and title prefix |
| `Time Limit` | Rich text | No | e.g. "1 second". Defaults to "1 second" if absent |
| `Memory Limit` | Rich text | No | e.g. "256 MB". Defaults to "256 MB" if absent |
| `Difficulty` | Select | No | e.g. "Easy", "Medium", "Hard". Shown as badge in UI |
| `Status` | Select | No | e.g. "Draft", "Ready". Used only for `NOTION_FILTER_STATUS` UI filtering — not for bundle control |

All property names are configurable via environment variables (see §10).

**Sorting:** Problems are sorted first by `Problem Letter` (alphabetically), then by `Name`. Problems without a letter appear last.

---

## 9. Notion Page Content Convention

### Title Convention

Problem titles must follow this format in the Notion Title field:

```
ชื่อภาษาไทย (English Name)
```

The English portion in parentheses is extracted by the application and used for ZIP filenames. Both parts are shown in the UI and in the PDF. If no parenthetical is present, the full title is used as the filename.

> **This convention is load-bearing.** Problem setters must follow it for correct ZIP file naming.

### Section Markers

Use **Heading 2** blocks in Notion to mark the start of each section. The heading text must match the following table exactly:

| Heading 2 text | Section | Match type |
|---|---|---|
| `ข้อมูลนำเข้า` | Input format | Exact Unicode |
| `ข้อมูลส่งออก` | Output format | Exact Unicode |
| `การให้คะแนน` | Scoring / constraints | Exact Unicode |
| `Constraints` | Scoring / constraints | Case-insensitive |
| `Sample Input/Output` | Sample I/O | Case-insensitive |

Everything before the first Heading 2 is automatically the `statement` section. No heading is needed for it.

**Any other Heading 2 text will cause that section's content to be dropped** from the PDF, and a warning will appear in the UI.

### Recommended Page Structure

```
[Problem narrative — no heading needed]
[paragraphs, images, math]

[Heading 2] ข้อมูลนำเข้า
[paragraphs describing input format]

[Heading 2] ข้อมูลส่งออก
[paragraphs describing output format]

[Heading 2] การให้คะแนน   ← or "Constraints"
[bullet list of subtasks / constraints]

[Heading 2] Sample Input/Output
[table with Input/Output columns]
```

### Math Notation

Write LaTeX-style math using `$...$` for inline and `$$...$$` for display (block) math:

- Inline: `ค่า $N$ อยู่ในช่วง $1 \le N \le 10^5$`
- Display: `$$\sum_{i=1}^{N} a_i \le 10^9$$`

Lone dollar signs in prose must be escaped: `\$`.

Only standard LaTeX math commands are supported. Custom macros (`\newcommand`, `\def`) are not.

### Sample I/O Convention

Use a **Notion table block** with two columns (`Input`, `Output`). This renders as an HTML table with monospace font and a border in the PDF.

Alternatively, use **code blocks** for raw input/output text.

### Images

Place Notion image blocks anywhere in the page body. They are automatically downloaded at render time and embedded into the PDF.

Notion supports two image sources:
- **Uploaded files** (`type: "file"`) — stored on Notion's CDN with a time-limited S3 URL (~1 hour expiry).
- **Embedded links** (`type: "external"`) — any public image URL.

Both are handled identically.

---

## 10. Configuration Reference

All configuration is done via environment variables. In development, place them in a `.env` file in the project root. In Docker, they are loaded via `env_file: .env` in `docker-compose.yml`.

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_PASSWORD` | ✅ Yes | — | Shared team password for HTTP Basic Auth. **Server refuses to start if unset.** |
| `NOTION_TOKEN` | ✅ Yes | — | Notion integration token. Get from https://www.notion.so/my-integrations |
| `NOTION_DATABASE_ID` | ✅ Yes | — | 32-char ID from the Notion database URL |
| `CONTEST_NAME` | No | `"Contest"` | Contest name shown in PDF page header |
| `CONTEST_DATES` | No | `""` | Date range shown in PDF page header |
| `SECTION_LANG` | No | `"th"` | Section heading language in PDF: `"th"` or `"en"` |
| `NOTION_PROP_TITLE` | No | `"Name"` | DB property name for problem title |
| `NOTION_PROP_LETTER` | No | `"Problem Letter"` | DB property name for problem letter |
| `NOTION_PROP_TIME` | No | `"Time Limit"` | DB property name for time limit |
| `NOTION_PROP_MEMORY` | No | `"Memory Limit"` | DB property name for memory limit |
| `NOTION_PROP_DIFFICULTY` | No | `"Difficulty"` | DB property name for difficulty |
| `NOTION_PROP_STATUS` | No | `"Status"` | DB property name for status |
| `NOTION_FILTER_STATUS` | No | `""` | If set, only show pages where Status equals this value in the UI. Does **not** affect the ZIP bundle — bundle inclusion is controlled by the in-app multi-select. |

### Getting the Database ID

From the Notion database URL:
```
https://www.notion.so/myworkspace/abc123def456789012345678901234ab?v=...
                                  └──────── this is the database ID ────┘
```

### Getting the Integration Token

1. Go to https://www.notion.so/my-integrations
2. Click **"+ New integration"**
3. Give it a name (e.g. "PDF Generator"), select your workspace
4. Copy the **"Internal Integration Token"** — it starts with `secret_`
5. In your Notion database, click **"⋯"** → **"Add connections"** → select your integration

---

## 11. API Reference

All endpoints require HTTP Basic Auth. Errors return JSON with HTTP 500 unless otherwise stated.

### `GET /`

Returns the web UI HTML page.

**Response:** `text/html`

### `GET /api/problems`

Returns all problems from the Notion database (filtered by `NOTION_FILTER_STATUS` if set).

**Response:** `application/json`

```json
[
  {
    "id": "abc12345-...",
    "title": "กลับบ้าน (Place To Call Home)",
    "letter": "A",
    "time_limit": "1 second",
    "memory_limit": "256 MB",
    "difficulty": "Medium",
    "status": "Ready",
    "last_edited_time": "2025-06-01T12:34:56.000Z"
  }
]
```

### `GET /api/problems/<page_id>/pdf`

Generates and downloads a PDF for a single problem. Checks the in-memory cache first.

**Response:** `application/pdf` with `Content-Disposition: attachment`

**Headers:** `X-PDF-Warnings: <pipe-separated warning strings>` (absent if no warnings)

**Timing:** Instant on cache hit. 1–5 seconds on cache miss.

### `DELETE /api/problems/<page_id>/cache`

Clears the cached PDF for a single problem.

**Response:** `{"ok": true}`

### `DELETE /api/problems/cache`

Clears the entire in-memory PDF cache.

**Response:** `{"cleared": <count>}`

### `POST /api/problems/bundle/stream`

Opens a Server-Sent Events stream. Generates PDFs for the specified problems sequentially.

**Request body:** `{"page_ids": ["abc123", "def456", ...]}`

**Response:** `text/event-stream`

Event format (one JSON object per `data:` line):

```
data: {"done": 0, "total": 5, "current": "กลับบ้าน", "status": "starting"}

data: {"done": 1, "total": 5, "current": "เส้นทาง", "status": "ok"}

data: {"done": 2, "total": 5, "current": "...", "status": "warning", "warnings": ["missing_image:fig1.png"]}

data: {"done": 5, "total": 5, "token": "a1b2c3d4e5f6", "status": "done"}
```

The `token` in the final event is valid for **60 seconds**.

### `GET /api/problems/bundle/download?token=<token>`

Exchanges a bundle token for the ZIP file.

**Response:** `application/zip` with `Content-Disposition: attachment; filename="contest_problems.zip"`

**Error:** HTTP 410 Gone if the token has expired or was already consumed.

**Timing:** Instant — the ZIP is pre-built by the SSE stream.

### ZIP Filename Convention

Files inside the ZIP are named from the **English portion of the bilingual title**:

| Notion title | ZIP filename |
|---|---|
| `กลับบ้าน (Place To Call Home)` | `Place_To_Call_Home.pdf` |
| `เส้นทางสั้นที่สุด (Shortest Path)` | `Shortest_Path.pdf` |
| `Two Sum` (no Thai) | `Two_Sum.pdf` |

Sanitisation: replace all characters outside `[a-zA-Z0-9_-]` with `_`, collapse consecutive underscores, strip leading/trailing underscores. If two problems sanitise to the same filename, append a numeric suffix: `Place_To_Call_Home_2.pdf`.

---

## 12. Docker & Deployment

### Dockerfile

```dockerfile
FROM python:3.12-slim

# WeasyPrint C library dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpango-1.0-0 \
    libpangoft2-1.0-0 \
    libpangocairo-1.0-0 \
    libcairo2 \
    libgdk-pixbuf-2.0-0 \
    libffi-dev \
    shared-mime-info \
    fonts-dejavu \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY server/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server/ .

EXPOSE 5000
# Use Gunicorn — NOT python app.py — in all containerised deployments
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "120", "app:app"]
```

### docker-compose.yml

```yaml
services:
  pdf-generator:
    build: .
    ports:
      - "127.0.0.1:5000:5000"   # Bind to localhost only — Caddy handles public access
    env_file:
      - .env
    restart: unless-stopped
    volumes:
      - ./server/templates:/app/templates   # Live-reload templates without rebuild
      - ./server/static:/app/static         # Supply logo.png from host filesystem
```

> **Why `127.0.0.1:5000`?** Binding to `0.0.0.0:5000` would expose port 5000 directly to the internet without TLS. Caddy handles the public-facing HTTPS connection and proxies to this local port.

### Internet-Facing Deployment: Caddy + TLS

For any deployment accessible over the internet, place the container behind **Caddy**, which provides automatic HTTPS via Let's Encrypt.

**`Caddyfile`** (place at project root):
```
your.domain.com {
    reverse_proxy localhost:5000
}
```

Start Caddy alongside the app:
```bash
caddy start --config Caddyfile
```

Or add it as a second service in `docker-compose.yml`:
```yaml
services:
  pdf-generator:
    # ... as above

  caddy:
    image: caddy:2
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile
      - caddy_data:/data
    depends_on:
      - pdf-generator

volumes:
  caddy_data:
```

### In-Memory PDF Cache

PDFs are cached in Gunicorn worker memory, keyed by `(page_id, last_edited_time)`.

- `last_edited_time` is returned by the Notion API and included in the `/api/problems` response.
- A cache hit returns bytes instantly — no Notion API calls, no WeasyPrint.
- A changed `last_edited_time` automatically invalidates the cache entry.
- Users can manually invalidate via the **"↺ Refresh"** button (per-problem) or **"Clear All Cache"** button (global).
- Cache is **per Gunicorn worker**: with 2 workers, a warm cache on one worker does not benefit requests routed to the other. Acceptable for 1–3 users.
- Cache is lost on server restart. Acceptable for a homelab.
- Worst-case memory: ~15 problems × ~3 MB = ~45 MB. Negligible.

### Running in Production

```bash
# First time setup
cp .env.example .env
# Edit .env — set APP_PASSWORD, NOTION_TOKEN, NOTION_DATABASE_ID

cp /path/to/your/logo.png server/static/logo.png

# Start
docker compose up -d

# View logs
docker compose logs -f

# Stop
docker compose down

# Rebuild after code changes
docker compose up -d --build

# Update logo (no rebuild needed — volume-mounted)
cp /path/to/new/logo.png server/static/logo.png
```

---

## 13. PDF Visual Design Specification

The PDF visual style is based on the **CodeAlgo 2025** contest problem format.

### Page Layout

| Property | Value |
|---|---|
| Paper size | A4 (210mm × 297mm) |
| Top margin | 3.2cm (accommodates running header) |
| Right margin | 2.5cm |
| Bottom margin | 2.5cm |
| Left margin | 2.5cm |

### Running Header (every page)

A horizontal strip across the top of every page:
- **Left:** Contest logo (`logo.png`) at 32pt height
- **Right:** Contest name (bold, 11pt) above contest dates (regular, 9pt)
- **Bottom edge:** 1.5px solid black horizontal rule

### Problem Title Block

- Large bold heading, 22pt, Bai Jamjuree
- If `letter` is set, prefixed as `A. Problem Name`
- Followed immediately by `time_limit, memory_limit` in regular 10.5pt text

### Body Text

- Font: Bai Jamjuree, 11pt
- Line height: 1.65
- Paragraphs have `text-indent: 2em` (first-line indent)

### Section Headings

Bold, 13pt. No border. Text is localised (Thai or English depending on `SECTION_LANG`).

### Sample I/O Table

Two-column table with header row:
- All borders: 1.5px solid black
- Cell padding: 5pt top/bottom, 14pt left/right
- Cell content: Noto Sans Mono (monospace), 10pt
- `white-space: pre` preserves indentation and spacing

### Page Number

Bottom-right of each page. A short horizontal rule above. Auto-incremented by CSS `counter(page)`.

---

## 14. Image Handling

### Step 1: Detection

During `_parse_blocks()`, when a block with `"type": "image"` is encountered, it is handled separately from text blocks.

### Step 2: URL Resolution

| Notion image type | URL location |
|---|---|
| `file` (Notion-hosted) | `block["image"]["file"]["url"]` — pre-signed S3, expires ~1 hour |
| `external` | `block["image"]["external"]["url"]` — public URL |

### Step 3: Download

`requests.get(url, timeout=15)` downloads the image bytes immediately. A unique placeholder is generated and stored in an `images` dict.

### Step 4: Placeholder Injection

```html
<img src="notion-img-a1b2c3d4e5f6..." alt="Caption text">
```

### Step 5: Base64 Embedding

In `pdf_generator.py`, before Jinja2 rendering:

```html
<img src="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAA..." alt="Caption text">
```

This makes the HTML fully self-contained.

### MIME Type Detection

MIME type is inferred from magic bytes:

| Magic bytes | Format |
|---|---|
| `\x89PNG` | `image/png` |
| `\xff\xd8` | `image/jpeg` |
| `RIFF....WEBP` (bytes 0–3 = `RIFF`, bytes 8–11 = `WEBP`) | `image/webp` |
| `GIF8` | `image/gif` |
| Anything else | **Treat as failed download — warn and skip** |

> The original fallback to `image/png` for unknown types is removed. It produced silently broken images in the PDF with no diagnostic output.

---

## 15. Error Handling Strategy

### Error & Warning Table

| Situation | Behaviour |
|---|---|
| Image download fails (network error, timeout, expired S3 URL) | Log with URL to stdout. Continue PDF generation. Add to `X-PDF-Warnings` header. |
| Image has unrecognised MIME type | Same as download failure — warn and skip. |
| Unrecognised Heading 2 encountered | Log the exact heading text. Continue. Add warning naming the dropped heading. |
| Notion API rate limit (HTTP 429) | Retry up to 3 times: backoff 1s, 2s, 4s. Raise after all retries fail. |
| `APP_PASSWORD` not set at startup | Log error and exit. Do not accept connections. |
| Notion database unreachable or required property missing at startup | Log descriptive error naming the missing property and exit. |
| Any other unhandled exception | Log full traceback to stdout. Return `{"error": "..."}` HTTP 500. |

### Warning Surfacing

PDF-generation warnings are returned in a response header:

```
X-PDF-Warnings: missing_image:figure1.png|unknown_section:ตัวอย่าง
```

The web UI reads this header after every PDF download and shows a **dismissible warning banner** per problem. A persistent **collapsible error/warning panel** in the page header accumulates all warnings and errors for the current session — nothing is lost if the user downloads multiple problems in sequence.

---

## 16. Math Rendering

Problem statements contain LaTeX-style inline and display math mixed with Thai and English prose.

### Why Server-Side Conversion

WeasyPrint cannot execute JavaScript, ruling out browser-side MathJax or KaTeX. Math is converted server-side using `latex2mathml`, which produces **MathML** that WeasyPrint renders natively via its Pango/Cairo backend. No additional system dependencies are required.

### Implementation

Add `latex2mathml` to `requirements.txt`. In `pdf_generator.py`, apply `_render_math()` to each section's HTML **after** Markdown conversion and **before** sections are passed to Jinja2:

```python
import re
from latex2mathml.converter import convert

def _render_math(html: str) -> str:
    # Process display math ($$...$$) before inline ($...$)
    html = re.sub(
        r'\$\$(.+?)\$\$',
        lambda m: convert(m.group(1), display="block"),
        html, flags=re.DOTALL
    )
    html = re.sub(
        r'\$(.+?)\$',
        lambda m: convert(m.group(1), display="inline"),
        html
    )
    return html
```

### Important Constraints

- `_render_math()` must **not** be applied inside fenced code blocks. Extract code block content before calling and restore it afterward, or apply per-section before code blocks are rendered.
- Only standard LaTeX math commands are supported. `\newcommand` and `\def` are not.
- Lone `$` in prose must be escaped as `\$` by problem setters.
- Thai characters immediately adjacent to math delimiters (e.g. `จำนวน$N$ตัว`) are handled correctly as long as delimiters are unambiguous.

---

## 17. Technology Primers

This section is for newcomers who want to understand the technologies used before building the application.

### 17.1 Python & pip

Python is the programming language used for the server. `pip` is Python's package manager.

```bash
pip install flask
pip install -r requirements.txt
```

**Why `requirements.txt`?** It locks all dependencies to specific versions, ensuring the application behaves the same on every machine and every Docker build.

**Virtual environments** (recommended for development):
```bash
python3 -m venv venv
source venv/bin/activate   # macOS/Linux
pip install -r server/requirements.txt
```

### 17.2 Flask

Flask is a "micro" web framework. It gives you routing and request handling.

```python
from flask import Flask, jsonify
app = Flask(__name__)

@app.route("/api/hello")
def hello():
    return jsonify({"message": "Hello!"})
```

Key concepts: `@app.route`, `request`, `jsonify`, `send_file`, `render_template`.

> **Important:** Never run Flask with `python app.py` in production. Use Gunicorn.

### 17.3 Gunicorn

Gunicorn is a production WSGI server for Python web applications. Unlike Flask's built-in dev server, it supports multiple concurrent workers.

```bash
gunicorn --workers 2 --bind 0.0.0.0:5000 --timeout 120 app:app
```

`app:app` means: in the file `app.py`, find the object named `app`.

### 17.4 Notion API

The Notion API is a REST API for reading and writing Notion data. The official Python SDK (`notion-client`) wraps the raw HTTP calls.

```python
from notion_client import Client
client = Client(auth="secret_xxx")

response = client.databases.query(database_id="xxx")
page = client.pages.retrieve(page_id="xxx")
response = client.blocks.children.list(block_id="xxx")
```

### 17.5 Markdown

Markdown is a lightweight text format. `python-markdown` converts it to HTML:

```python
import markdown
html = markdown.markdown("**Hello** $N$ world", extensions=["extra", "nl2br", "sane_lists"])
```

### 17.6 Jinja2 Templating

Jinja2 fills HTML templates with dynamic values:

```html
<h1>{{ title }}</h1>
{% if letter %}<span>{{ letter }}.</span>{% endif %}
{{ content | safe }}
```

The `| safe` filter is critical: it tells Jinja2 to insert HTML strings as-is rather than escaping them.

### 17.7 WeasyPrint (HTML → PDF)

WeasyPrint renders HTML+CSS to PDF using the same model as a web browser, but outputs pages.

```python
from weasyprint import HTML
pdf_bytes = HTML(string=html, base_url="/path/to/static/").write_pdf()
```

WeasyPrint implements CSS Paged Media — a W3C standard for print-specific CSS features (running headers, page counters, margin areas). It also renders MathML natively.

**System dependencies:** WeasyPrint calls C libraries (Cairo, Pango) for rendering. These are installed via `apt-get` in the Dockerfile.

### 17.8 Docker & Docker Compose

Docker packages the application and all its dependencies into a portable **container**.

| Concept | Description |
|---|---|
| Image | Read-only snapshot of the container filesystem |
| Container | A running instance of an image |
| Dockerfile | Instructions for building an image |
| Volume | Maps a host directory into the container |

```bash
docker compose up -d        # Start in background
docker compose down         # Stop
docker compose logs -f      # Stream logs
docker compose up -d --build  # Rebuild and start
```

---

## 18. Development Guide

### Prerequisites

- Python 3.12+
- Docker and Docker Compose
- A Notion account with an integration token and a database
- (For internet deployment) A domain name and Caddy

### Running Locally (Without Docker)

```bash
# 1. Set up the project
cd notion-to-pdf

# 2. Create virtual environment
python3 -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate

# 3. Install Python dependencies
pip install -r server/requirements.txt

# 4. Install WeasyPrint system dependencies
# macOS:
brew install pango cairo gdk-pixbuf libffi
# Ubuntu/Debian:
sudo apt-get install libpango-1.0-0 libpangoft2-1.0-0 libpangocairo-1.0-0 \
  libcairo2 libgdk-pixbuf-2.0-0 libffi-dev fonts-dejavu

# 5. Set up environment
cp .env.example .env
# Edit .env — set APP_PASSWORD, NOTION_TOKEN, NOTION_DATABASE_ID

# 6. Add your logo
cp /path/to/logo.png server/static/logo.png

# 7. Run with Flask dev server (development only — never in production)
cd server
set -a && source ../.env && set +a
python app.py
# → http://localhost:5000
```

### Running with Docker (Recommended)

```bash
cp .env.example .env
# Edit .env

cp /path/to/logo.png server/static/logo.png

docker compose up -d
# → http://localhost:5000
```

### Editing the PDF Template

1. Open `server/templates/problem.html`.
2. Edit the CSS in the `<style>` block.
3. Click "⬇ PDF" on any problem — changes are reflected immediately (templates are volume-mounted, no rebuild needed).

### Common Development Tasks

**Add a new section type:**
1. In `notion_client_wrapper.py`, add the new keyword to the heading detection table in `_parse_blocks()`.
2. In `pdf_generator.py`, add the new label to both `_LABELS` dicts.
3. In `problem.html`, add a new `{% if sections.newsection %}` block.

**Change the sort order:**  
In `notion_client_wrapper.py`, modify the `results.sort(...)` line in `list_problems()`.

**Add a new Notion block type:**  
In `notion_client_wrapper.py`, add a new `if btype == "..."` branch in `_block_to_markdown()`.

---

## 19. Extending the Application

### Add a Preview Mode (HTML in Browser)

Return rendered HTML for quick in-browser preview without generating a PDF:

```python
@app.route("/api/problems/<page_id>/preview")
@auth.login_required
def preview_problem(page_id):
    problem = notion.get_problem(page_id)
    sections = {k: _render_math(md.markdown(v, extensions=["extra","nl2br","sane_lists"]))
                for k, v in problem["sections"].items()}
    template = _jinja_env.get_template("problem.html")
    html = template.render(
        title=problem["title_full"], letter=problem["letter"],
        time_limit=problem["time_limit"], memory_limit=problem["memory_limit"],
        contest_name=CONTEST_NAME, contest_dates=CONTEST_DATES,
        sections=sections, labels=_LABELS[SECTION_LANG], static_dir=STATIC_DIR
    )
    return html, 200, {"Content-Type": "text/html"}
```

### Support Multiple Contests / Databases

Add a `NOTION_DATABASE_ID_2` env var and a second `NotionClient` instance. Add a contest switcher to the UI.

### Offline Font Loading

If the homelab has no internet access, download the Bai Jamjuree font files and serve them locally:

1. Download `.ttf` files from https://fonts.google.com/specimen/Bai+Jamjuree
2. Place them in `server/static/fonts/`
3. Replace the `@import` in `problem.html` with local `@font-face` declarations:

```css
@font-face {
  font-family: 'Bai Jamjuree';
  src: url('fonts/BaiJamjuree-Regular.ttf') format('truetype');
  font-weight: 400;
}
@font-face {
  font-family: 'Bai Jamjuree';
  src: url('fonts/BaiJamjuree-Bold.ttf') format('truetype');
  font-weight: 700;
}
```
