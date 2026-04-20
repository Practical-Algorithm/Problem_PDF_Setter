# Contest PDF Generator

A self-hosted web tool that pulls competitive programming problems from a Notion database and renders them as print-ready PDFs.

Problem setters write problem statements directly in Notion (with full support for LaTeX math, tables, images, and code blocks), then use this tool to generate consistently-formatted PDFs for individual problems or the entire problem set as a ZIP bundle.

---

## Features

- **Notion integration** — reads problem content and metadata (title, letter, time/memory limits, difficulty, status) directly from a Notion database
- **LaTeX math rendering** — `$inline$` and `$$display$$` math is converted to MathML using `latex2mathml`
- **Markdown body** — paragraphs, bold/italic, code blocks, lists, tables, blockquotes, callouts, and images are all supported
- **Customisable PDF template** — edit `problem.html` from the browser without restarting the server; saving the template automatically clears the PDF cache
- **PDF cache** — generated PDFs are cached per `(page_id, last_edited_time)`; a green dot in the UI shows which problems are ready instantly
- **ZIP bundle** — select any subset of problems and download them all as a single ZIP with a live progress log
- **Warning panel** — missing images or unrecognised section headings are surfaced per-problem without blocking the download
- **Basic auth** — all routes are protected with HTTP Basic Authentication
- **Docker-ready** — single `docker-compose up` to run; templates and static assets are mounted as volumes for live editing

---

## Notion page structure

Each problem is a Notion page in a single database. The page body uses **Heading 2** blocks as section dividers. The following headings are recognised:

| Heading text | Section |
|---|---|
| *(top of page, before any heading)* | Statement |
| `ข้อมูลนำเข้า` | Input |
| `ข้อมูลส่งออก` | Output |
| `การให้คะแนน` | Constraints / Scoring |
| `Constraints` *(case-insensitive)* | Constraints |
| `Sample Input/Output` *(case-insensitive)* | Examples |

Heading 1 blocks are silently ignored (useful for page-level decorators in Notion). Any unrecognised Heading 2 is reported as a warning.

Database properties read by the tool:

| Property | Default name | Notes |
|---|---|---|
| Title | `Name` | Bilingual titles use the format `Thai title (English title)` |
| Problem letter | `Problem Letter` | Shown as a badge in the UI and on the PDF |
| Time limit | `Time Limit` | Plain text, e.g. `2 seconds` |
| Memory limit | `Memory Limit` | Plain text, e.g. `256 MB` |
| Difficulty | `Difficulty` | Select property; `Easy` / `Medium` / `Hard` get colour-coded badges |
| Status | `Story` | Select property; optionally used to filter which problems appear |

All property names are configurable via environment variables.

---

## Quick start

### 1. Create a Notion integration

1. Go to [notion.so/my-integrations](https://www.notion.so/my-integrations) and create a new internal integration.
2. Copy the **Internal Integration Token**.
3. Open your problems database in Notion, click the `...` menu → **Connections** → add your integration.

### 2. Configure environment variables

Copy `.env.example` to `.env` and fill in the values:

```env
NOTION_TOKEN=ntn_...
NOTION_DATABASE_ID=<your-database-id>
APP_PASSWORD=<choose-a-strong-password>

# Optional
CONTEST_NAME=My Contest 2025
CONTEST_DATES=25–26 April 2025
SECTION_LANG=th           # "th" (default) or "en" — controls section label language in PDFs

# Optional: override Notion property names
NOTION_PROP_TITLE=Name
NOTION_PROP_LETTER=Problem Letter
NOTION_PROP_TIME=Time Limit
NOTION_PROP_MEMORY=Memory Limit
NOTION_PROP_DIFFICULTY=Difficulty
NOTION_PROP_STATUS=Story

# Optional: filter to only show problems with a specific status value
NOTION_FILTER_STATUS=Ready
```

### 3. Add a logo (optional)

Place a `logo.png` file in `server/static/`. It will be used in the PDF header via the template.

### 4. Run

```bash
docker compose up --build
```

The app is available at `http://localhost:5000`. Log in with username `team` and the password from `APP_PASSWORD`.

---

## Development

Run the Flask dev server directly (no Docker):

```bash
cd server
pip install -r requirements.txt
python app.py
```

A `.development.env` file can be used for local secrets (the app loads `.env` from the project root).

---

## PDF template

The PDF is rendered from `server/templates/problem.html` via [WeasyPrint](https://weasyprint.org/). The template receives these Jinja2 variables:

| Variable | Type | Description |
|---|---|---|
| `title` | `str` | Full problem title |
| `letter` | `str` | Problem letter (e.g. `A`) |
| `time_limit` | `str` | Time limit string |
| `memory_limit` | `str` | Memory limit string |
| `contest_name` | `str` | From `CONTEST_NAME` env var |
| `contest_dates` | `str` | From `CONTEST_DATES` env var |
| `sections` | `dict` | Keys: `statement`, `input`, `output`, `constraints`, `examples` — values are rendered HTML strings |
| `labels` | `dict` | Localised section heading strings |
| `static_dir` | `str` | Absolute path to `server/static/` for font and image references |

The template can be edited live from the **Edit Template** button in the UI; saving it automatically invalidates the PDF cache.

---

## Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.12, Flask, Gunicorn |
| PDF rendering | WeasyPrint |
| Math | latex2mathml (LaTeX → MathML) |
| Markdown | Python-Markdown (`extra`, `nl2br`, `sane_lists`) |
| Notion API | notion-client 2.2.1 |
| Container | Docker + Docker Compose |
