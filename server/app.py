import io
import json
import os
import re
import threading
import time
import uuid
import zipfile

from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context
from flask_httpauth import HTTPBasicAuth

from notion_client_wrapper import (
    PROP_LETTER,
    PROP_MEMORY,
    PROP_TIME,
    PROP_TITLE,
    NotionClientWrapper,
    _notion_call_with_retry,
)
from pdf_generator import generate_pdf, TEMPLATES_DIR, CONTEST_NAME

# ---------------------------------------------------------------------------
# App & auth setup
# ---------------------------------------------------------------------------

app  = Flask(__name__)
auth = HTTPBasicAuth()

APP_PASSWORD = os.environ.get("APP_PASSWORD", "")
_USERS       = {"team": APP_PASSWORD}

NOTION_DATABASE_ID = os.environ.get("NOTION_DATABASE_ID", "")

notion = NotionClientWrapper()


@auth.verify_password
def verify(username, password):
    stored = _USERS.get(username)
    if not stored:
        return False
    return stored == password


# ---------------------------------------------------------------------------
# In-memory caches (per Gunicorn worker)
# ---------------------------------------------------------------------------

# key: (page_id_normalised, last_edited_time) -> {"pdf": bytes, "warnings": list}
_pdf_cache:  dict = {}
_cache_lock: threading.Lock = threading.Lock()

# token -> {"zip": bytes, "expiry": float}
_bundle_tokens:      dict = {}
_bundle_tokens_lock: threading.Lock = threading.Lock()


def _normalise_id(page_id: str) -> str:
    return page_id.replace("-", "")


def _sanitize_filename(name: str) -> str:
    """Return a safe filename base (no extension)."""
    name = re.sub(r"[^a-zA-Z0-9_\-]", "_", name)
    name = re.sub(r"_+", "_", name)
    name = name.strip("_")
    return name or "problem"


# ---------------------------------------------------------------------------
# Startup validation
# ---------------------------------------------------------------------------

def validate_startup() -> None:
    if not APP_PASSWORD:
        raise RuntimeError(
            "APP_PASSWORD environment variable is not set. Refusing to start."
        )

    try:
        db = _notion_call_with_retry(notion.client.databases.retrieve, database_id=NOTION_DATABASE_ID)
    except Exception as e:
        raise RuntimeError(f"Cannot reach Notion database '{NOTION_DATABASE_ID}': {e}")

    obj_type = db.get("object", "unknown")
    if obj_type != "database":
        raise RuntimeError(
            f"NOTION_DATABASE_ID does not point to a database (got '{obj_type}'). "
            f"Verify the ID and that the integration has been added to the database in Notion."
        )

    app.logger.info(f"Notion database reachable. Title: {db.get('title', [{}])[0].get('plain_text', '(untitled)')}")


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route("/")
@auth.login_required
def index():
    return render_template("index.html", contest_name=CONTEST_NAME)


@app.route("/api/problems")
@auth.login_required
def list_problems():
    try:
        problems = notion.list_problems()
        return jsonify(problems)
    except Exception as e:
        app.logger.exception("Error listing problems")
        return jsonify({"error": str(e)}), 500


@app.route("/api/problems/<page_id>/pdf")
@auth.login_required
def get_problem_pdf(page_id):
    try:
        norm_id = _normalise_id(page_id)

        # Lightweight metadata fetch for the cache key
        page_meta    = _notion_call_with_retry(notion.client.pages.retrieve, page_id=page_id)
        last_edited  = page_meta.get("last_edited_time", "")
        cache_key    = (norm_id, last_edited)

        with _cache_lock:
            cached = _pdf_cache.get(cache_key)

        if cached:
            resp = send_file(
                io.BytesIO(cached["pdf"]),
                mimetype="application/pdf",
                as_attachment=True,
                download_name=f"{norm_id}.pdf",
            )
            if cached.get("warnings"):
                resp.headers["X-PDF-Warnings"] = "|".join(cached["warnings"])
            return resp

        # Cache miss — generate PDF
        problem   = notion.get_problem(page_id)
        pdf_bytes = generate_pdf(problem)
        warnings  = problem.get("warnings", [])

        with _cache_lock:
            _pdf_cache[cache_key] = {"pdf": pdf_bytes, "warnings": warnings}

        title_en  = problem.get("title_en", page_id)
        safe_name = _sanitize_filename(title_en)

        resp = send_file(
            io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"{safe_name}.pdf",
        )
        if warnings:
            resp.headers["X-PDF-Warnings"] = "|".join(warnings)
        return resp

    except Exception as e:
        app.logger.exception(f"Error generating PDF for {page_id}")
        return jsonify({"error": str(e)}), 500


# Order matters: literal "cache" must be registered before <page_id> routes
@app.route("/api/problems/cache", methods=["DELETE"])
@auth.login_required
def clear_all_cache():
    try:
        with _cache_lock:
            count = len(_pdf_cache)
            _pdf_cache.clear()
        return jsonify({"cleared": count})
    except Exception as e:
        app.logger.exception("Error clearing all cache")
        return jsonify({"error": str(e)}), 500


@app.route("/api/problems/<page_id>/cache", methods=["DELETE"])
@auth.login_required
def clear_problem_cache(page_id):
    try:
        norm_id = _normalise_id(page_id)
        with _cache_lock:
            keys_to_delete = [k for k in _pdf_cache if k[0] == norm_id]
            for k in keys_to_delete:
                del _pdf_cache[k]
        return jsonify({"ok": True})
    except Exception as e:
        app.logger.exception(f"Error clearing cache for {page_id}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/problems/bundle/stream", methods=["POST"])
@auth.login_required
def bundle_stream():
    data     = request.get_json(force=True) or {}
    page_ids = data.get("page_ids", [])

    def generate():
        zip_buffer     = io.BytesIO()
        used_filenames = set()

        yield f"data: {json.dumps({'done': 0, 'total': len(page_ids), 'current': '', 'status': 'starting'})}\n\n"

        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            for i, page_id in enumerate(page_ids):
                try:
                    problem   = notion.get_problem(page_id)
                    title     = problem.get("title_full", page_id)
                    title_en  = problem.get("title_en",   page_id)
                    last_edited = problem.get("last_edited_time", "")
                    norm_id     = _normalise_id(page_id)
                    cache_key   = (norm_id, last_edited)

                    yield f"data: {json.dumps({'done': i, 'total': len(page_ids), 'current': title, 'status': 'generating'})}\n\n"

                    with _cache_lock:
                        cached = _pdf_cache.get(cache_key)

                    if cached:
                        pdf_bytes = cached["pdf"]
                        warnings  = cached.get("warnings", [])
                    else:
                        pdf_bytes = generate_pdf(problem)
                        warnings  = problem.get("warnings", [])
                        with _cache_lock:
                            _pdf_cache[cache_key] = {"pdf": pdf_bytes, "warnings": warnings}

                    # Build unique ZIP filename
                    base_name = _sanitize_filename(title_en)
                    filename  = f"{base_name}.pdf"
                    if filename in used_filenames:
                        counter = 2
                        while f"{base_name}_{counter}.pdf" in used_filenames:
                            counter += 1
                        filename = f"{base_name}_{counter}.pdf"
                    used_filenames.add(filename)
                    zf.writestr(filename, pdf_bytes)

                    status = "warning" if warnings else "ok"
                    event  = {"done": i + 1, "total": len(page_ids), "current": title, "status": status}
                    if warnings:
                        event["warnings"] = warnings
                    yield f"data: {json.dumps(event)}\n\n"

                except Exception as e:
                    app.logger.exception(f"Error generating PDF for {page_id} in bundle")
                    yield f"data: {json.dumps({'done': i + 1, 'total': len(page_ids), 'current': page_id, 'status': 'error', 'error': str(e)})}\n\n"

        zip_bytes = zip_buffer.getvalue()
        token     = uuid.uuid4().hex
        expiry    = time.time() + 60

        with _bundle_tokens_lock:
            _bundle_tokens[token] = {"zip": zip_bytes, "expiry": expiry}

        yield f"data: {json.dumps({'done': len(page_ids), 'total': len(page_ids), 'token': token, 'status': 'done'})}\n\n"

    return Response(
        stream_with_context(generate()),
        content_type="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@app.route("/api/problems/bundle/download")
@auth.login_required
def bundle_download():
    token = request.args.get("token", "")
    with _bundle_tokens_lock:
        entry = _bundle_tokens.get(token)
        if not entry:
            return jsonify({"error": "Token not found or already consumed"}), 410
        if time.time() > entry["expiry"]:
            del _bundle_tokens[token]
            return jsonify({"error": "Token expired"}), 410
        zip_bytes = entry["zip"]
        del _bundle_tokens[token]

    return send_file(
        io.BytesIO(zip_bytes),
        mimetype="application/zip",
        as_attachment=True,
        download_name="contest_problems.zip",
    )


# ---------------------------------------------------------------------------
# Template editor
# ---------------------------------------------------------------------------

_TEMPLATE_FILE = os.path.join(TEMPLATES_DIR, "problem.html")


@app.route("/api/template", methods=["GET"])
@auth.login_required
def get_template():
    with open(_TEMPLATE_FILE, "r", encoding="utf-8") as f:
        content = f.read()
    return jsonify({"content": content})


@app.route("/api/template", methods=["PUT"])
@auth.login_required
def update_template():
    data = request.get_json(force=True) or {}
    content = data.get("content")
    if content is None:
        return jsonify({"error": "content is required"}), 400
    with open(_TEMPLATE_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    # Invalidate PDF cache so next generation uses the new template
    with _cache_lock:
        _pdf_cache.clear()
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------

validate_startup()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
