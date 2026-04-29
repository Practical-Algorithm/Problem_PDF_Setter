import os
import re
import time
import uuid
import requests
from notion_client import Client
from notion_client.errors import APIResponseError

PROP_TITLE      = os.environ.get("NOTION_PROP_TITLE",      "Name")
PROP_LETTER     = os.environ.get("NOTION_PROP_LETTER",     "Problem Letter")
PROP_TIME       = os.environ.get("NOTION_PROP_TIME",       "Time Limit")
PROP_MEMORY     = os.environ.get("NOTION_PROP_MEMORY",     "Memory Limit")
PROP_DIFFICULTY = os.environ.get("NOTION_PROP_DIFFICULTY", "Difficulty")
PROP_STATUS     = os.environ.get("NOTION_PROP_STATUS",     "Story")

NOTION_DATABASE_ID   = os.environ.get("NOTION_DATABASE_ID", "")
NOTION_FILTER_STATUS = os.environ.get("NOTION_FILTER_STATUS", "")

# Exact Thai headings map to section keys; English variants matched case-insensitively
_SECTION_MAP_EXACT = {
    "ข้อมูลนำเข้า": "input",
    "ข้อมูลส่งออก": "output",
    "การให้คะแนน":  "constraints",
}
_SECTION_MAP_LOWER = {
    "constraints":        "constraints",
    "sample input/output": "examples",
}


_NOTION_API_VERSION = "2022-06-28"


def _notion_call_with_retry(fn, *args, **kwargs):
    for attempt in range(4):  # 1 attempt + 3 retries
        try:
            return fn(*args, **kwargs)
        except APIResponseError as e:
            if e.status == 429 and attempt < 3:
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
                continue
            raise


def _query_database(database_id: str, body: dict) -> dict:
    """POST /v1/databases/{id}/query via requests (databases.query removed in newer SDK)."""
    token = os.environ.get("NOTION_TOKEN", "")
    for attempt in range(4):
        resp = requests.post(
            f"https://api.notion.com/v1/databases/{database_id}/query",
            headers={
                "Authorization": f"Bearer {token}",
                "Notion-Version": _NOTION_API_VERSION,
                "Content-Type": "application/json",
            },
            json=body,
            timeout=30,
        )
        if resp.status_code == 429 and attempt < 3:
            time.sleep(2 ** attempt)
            continue
        resp.raise_for_status()
        return resp.json()
    resp.raise_for_status()  # final raise if all retries exhausted on 429


def _parse_title(raw_title: str) -> dict:
    match = re.search(r'\(([^)]+)\)\s*$', raw_title.strip())
    if match:
        return {
            "title_full": raw_title.strip(),
            "title_en":   match.group(1).strip(),
        }
    return {
        "title_full": raw_title.strip(),
        "title_en":   raw_title.strip(),
    }


def _rich_text_to_markdown(rich_text_list: list) -> str:
    parts = []
    for rt in rich_text_list:
        # Notion inline equations have type "equation" — wrap in $...$
        if rt.get("type") == "equation":
            expr = rt.get("equation", {}).get("expression", rt.get("plain_text", ""))
            parts.append(f"${expr}$")
            continue

        text = rt.get("plain_text", "")
        ann  = rt.get("annotations", {})
        bold   = ann.get("bold",   False)
        italic = ann.get("italic", False)
        code   = ann.get("code",   False)
        if code:
            text = f"`{text}`"
        elif bold and italic:
            text = f"***{text}***"
        elif bold:
            text = f"**{text}**"
        elif italic:
            text = f"*{text}*"
        parts.append(text)
    return "".join(parts)


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


def _find_title_prop(props: dict) -> dict:
    """Return the title-type property dict, regardless of its display name."""
    # Try the configured name first
    candidate = props.get(PROP_TITLE, {})
    if candidate.get("type") == "title":
        return candidate
    # Fallback: scan for any property whose type is "title"
    for prop in props.values():
        if prop.get("type") == "title":
            return prop
    return {}


def _get_rich_text_value(props: dict, key: str, default: str = "") -> str:
    prop = props.get(key, {})
    if prop.get("type") == "rich_text":
        return "".join(rt.get("plain_text", "") for rt in prop.get("rich_text", []))
    return default


class NotionClientWrapper:
    def __init__(self):
        token = os.environ.get("NOTION_TOKEN", "")
        self.client = Client(auth=token)
        self.database_id = NOTION_DATABASE_ID

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_problems(self) -> list:
        results = []
        cursor  = None
        filter_params = {}
        if NOTION_FILTER_STATUS:
            filter_params = {
                "filter": {
                    "property": PROP_STATUS,
                    "select":   {"equals": NOTION_FILTER_STATUS},
                }
            }

        while True:
            body = {**filter_params}
            if cursor:
                body["start_cursor"] = cursor
            response = _query_database(self.database_id, body)
            results.extend(response["results"])
            if not response.get("has_more"):
                break
            cursor = response["next_cursor"]

        problems = []
        for page in results:
            props = page["properties"]

            title_prop = _find_title_prop(props)
            raw_title  = "".join(
                rt.get("plain_text", "") for rt in title_prop.get("title", [])
            )
            title_info = _parse_title(raw_title)

            letter      = _get_rich_text_value(props, PROP_LETTER)
            time_limit  = _get_rich_text_value(props, PROP_TIME,   "1 second") or "1 second"
            memory_limit= _get_rich_text_value(props, PROP_MEMORY, "256 MB")   or "256 MB"

            diff_prop   = props.get(PROP_DIFFICULTY, {})
            difficulty  = ""
            if diff_prop.get("type") == "select" and diff_prop.get("select"):
                difficulty = diff_prop["select"].get("name", "")

            stat_prop   = props.get(PROP_STATUS, {})
            status      = ""
            if stat_prop.get("type") == "select" and stat_prop.get("select"):
                status = stat_prop["select"].get("name", "")

            problems.append({
                "id":               page["id"],
                "title":            title_info["title_full"],
                "title_en":         title_info["title_en"],
                "letter":           letter,
                "time_limit":       time_limit,
                "memory_limit":     memory_limit,
                "difficulty":       difficulty,
                "status":           status,
                "last_edited_time": page.get("last_edited_time", ""),
            })

        # Sort: by letter (ascending), then by title; letter-less problems last
        def sort_key(p):
            ltr = p["letter"].upper() if p["letter"] else None
            return (0 if ltr else 1, ltr or "", p["title"])

        problems.sort(key=sort_key)
        return problems

    def get_problem(self, page_id: str) -> dict:
        page  = _notion_call_with_retry(self.client.pages.retrieve, page_id=page_id)
        props = page["properties"]

        title_prop   = _find_title_prop(props)
        raw_title    = "".join(
            rt.get("plain_text", "") for rt in title_prop.get("title", [])
        )
        title_info   = _parse_title(raw_title)
        letter       = _get_rich_text_value(props, PROP_LETTER)
        time_limit   = _get_rich_text_value(props, PROP_TIME,   "1 second") or "1 second"
        memory_limit = _get_rich_text_value(props, PROP_MEMORY, "256 MB")   or "256 MB"

        all_blocks = self._all_blocks(page_id)
        sections, images, warnings = self._parse_blocks(all_blocks)

        return {
            "id":               page_id,
            "title_full":       title_info["title_full"],
            "title_en":         title_info["title_en"],
            "letter":           letter,
            "time_limit":       time_limit,
            "memory_limit":     memory_limit,
            "sections":         sections,
            "images":           images,
            "warnings":         warnings,
            "last_edited_time": page.get("last_edited_time", ""),
        }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _all_blocks(self, block_id: str) -> list:
        blocks = []
        cursor = None
        while True:
            kwargs = {"block_id": block_id}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = _notion_call_with_retry(self.client.blocks.children.list, **kwargs)
            blocks.extend(response["results"])
            if not response.get("has_more"):
                break
            cursor = response["next_cursor"]
        return blocks

    def _parse_blocks(self, blocks: list) -> tuple:
        section_order = ["statement", "input", "output", "constraints", "examples"]
        section_lines = {s: [] for s in section_order}
        images   = {}
        warnings = []

        current_section = "statement"

        for block in blocks:
            btype = block.get("type", "")

            if btype in ("heading_1", "heading_2"):
                # Not used as section separators — skip silently
                continue

            if btype == "heading_3":
                heading_text = "".join(
                    rt.get("plain_text", "")
                    for rt in block["heading_3"].get("rich_text", [])
                ).strip()
                if heading_text in _SECTION_MAP_EXACT:
                    current_section = _SECTION_MAP_EXACT[heading_text]
                elif heading_text.lower() in _SECTION_MAP_LOWER:
                    current_section = _SECTION_MAP_LOWER[heading_text.lower()]
                else:
                    warnings.append(f"unknown_section:{heading_text}")
                    current_section = None  # drop content until next recognised heading
                continue

            if current_section is None:
                continue

            md = self._block_to_markdown(block, images, warnings)
            if md is not None:
                section_lines[current_section].append(md)

        sections = {s: "\n\n".join(section_lines[s]) for s in section_order}
        return sections, images, warnings

    def _block_to_markdown(self, block: dict, images: dict, warnings: list):
        btype = block.get("type", "")

        if btype == "paragraph":
            return _rich_text_to_markdown(block["paragraph"].get("rich_text", []))

        if btype == "bulleted_list_item":
            text = _rich_text_to_markdown(block["bulleted_list_item"].get("rich_text", []))
            return f"- {text}"

        if btype == "numbered_list_item":
            text = _rich_text_to_markdown(block["numbered_list_item"].get("rich_text", []))
            return f"1. {text}"

        if btype == "code":
            lang = block["code"].get("language", "")
            text = "".join(
                rt.get("plain_text", "") for rt in block["code"].get("rich_text", [])
            )
            return f"```{lang}\n{text}\n```"

        if btype == "quote":
            text = _rich_text_to_markdown(block["quote"].get("rich_text", []))
            return f"> {text}"

        if btype == "callout":
            text = _rich_text_to_markdown(block["callout"].get("rich_text", []))
            return f"> **Note:** {text}"

        if btype == "equation":
            expr = block["equation"].get("expression", "")
            return f"$${expr}$$"

        if btype == "divider":
            return "---"

        if btype == "table":
            return self._table_to_markdown(block)

        if btype == "image":
            return self._fetch_image(block, images, warnings)

        # Unsupported block types silently skipped
        return None

    def _table_to_markdown(self, table_block: dict) -> str:
        rows   = []
        cursor = None
        table_id = table_block["id"]

        while True:
            kwargs = {"block_id": table_id}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = _notion_call_with_retry(self.client.blocks.children.list, **kwargs)
            rows.extend(response["results"])
            if not response.get("has_more"):
                break
            cursor = response["next_cursor"]

        if not rows:
            return ""

        def _cell(cells, idx):
            return _rich_text_to_markdown(cells[idx]) if idx < len(cells) else ""

        parsed = [
            (_cell(r.get("table_row", {}).get("cells", []), 0),
             _cell(r.get("table_row", {}).get("cells", []), 1))
            for r in rows
        ]

        header = parsed[0]
        data   = parsed[1:]

        # Notion may split a logical test-case row into multiple table rows:
        # continuation input lines appear as col1-only rows, and the final
        # row carries both the last input line and the (possibly multiline)
        # output.  Accumulate col1/col2 lines and flush when a both-filled
        # row is encountered (it ends the group, not starts a new one).
        groups = []
        pending_col1, pending_col2 = [], []

        for col1, col2 in data:
            if col1.strip() and col2.strip():
                pending_col1.append(col1)
                pending_col2.append(col2)
                groups.append(("\n".join(pending_col1), "\n".join(pending_col2)))
                pending_col1, pending_col2 = [], []
            elif col1.strip():
                pending_col1.append(col1)
            elif col2.strip():
                pending_col2.append(col2)

        if pending_col1 or pending_col2:
            groups.append(("\n".join(pending_col1), "\n".join(pending_col2)))

        # Emit as a raw HTML table so newlines inside cells are preserved
        # by the CSS `white-space: pre` rule on table td/th elements.
        html = ["<table>"]
        html.append(f"<tr><th>{header[0]}</th><th>{header[1]}</th></tr>")
        for col1, col2 in groups:
            html.append(f"<tr><td>{col1}</td><td>{col2}</td></tr>")
        html.append("</table>")
        return "".join(html)

    def _fetch_image(self, block: dict, images: dict, warnings: list) -> str:
        img      = block.get("image", {})
        img_type = img.get("type", "")
        caption  = "".join(
            rt.get("plain_text", "") for rt in img.get("caption", [])
        )

        if img_type == "file":
            url = img["file"]["url"]
        elif img_type == "external":
            url = img["external"]["url"]
        else:
            warnings.append("missing_image:unknown")
            return ""

        try:
            resp = requests.get(url, timeout=15)
            resp.raise_for_status()
            img_bytes = resp.content
        except Exception:
            short_name = url.split("/")[-1].split("?")[0]
            warnings.append(f"missing_image:{short_name}")
            return ""

        mime = _detect_mime(img_bytes)
        if mime is None:
            short_name = url.split("/")[-1].split("?")[0]
            warnings.append(f"missing_image:{short_name}")
            return ""

        placeholder = f"notion-img-{uuid.uuid4().hex}"
        images[placeholder] = img_bytes
        return f'<img src="{placeholder}" alt="{caption}">'
