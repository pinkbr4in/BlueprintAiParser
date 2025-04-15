import sys
import json
import markdown
import bleach
import re
import uuid
import os
from datetime import datetime
import html
# --- Flask imports ---
from flask import render_template, request, jsonify, current_app, session
from markupsafe import Markup
import traceback

# Import werkzeug exceptions
try:
    import werkzeug.exceptions
except ImportError:
    werkzeug = None

# --- CSRF imports ---
try:
    from flask_wtf.csrf import CSRFError
    from app import csrf
except ImportError:
    CSRFError = None
    csrf = None
    print("WARNING (routes.py): Flask-WTF or CSRF object not available.")

# --- Celery and Task imports ---
try:
    from celery_app import celery
    from tasks import parse_blueprint_task
    print("INFO (routes.py): Successfully imported celery and parse_blueprint_task.")
except ImportError as import_err:
    print(f"ERROR (routes.py): Failed to import Celery/Task: {import_err}")
    celery = None
    parse_blueprint_task = None

# --- Import the function to add chunked routes ---
try:
    from chunked_upload import add_chunked_upload_routes
    CHUNKED_UPLOAD_ENABLED = True
    print("INFO (routes.py): Imported chunked upload routes.")
except ImportError:
    add_chunked_upload_routes = None
    CHUNKED_UPLOAD_ENABLED = False
    print("ERROR (routes.py): Failed to import chunked upload routes.")

# ==============================================================================
# Main Function to Register Routes
# ==============================================================================
def register_routes(app):

    # --- Helper functions (defined within register_routes scope - from target) ---
    def html_escape(text):
        """Escapes text for use in HTML attribute values."""
        if not text:
            return ""
        return html.escape(text, quote=True)

    def clean_html_entities(html_content):
        """Normalize HTML entities to prevent double escaping."""
        replacements = [
            ('&lt;', '<'), ('&gt;', '>'), ('&amp;', '&'),
            ('&quot;', '"'), ('&#39;', "'")
        ]
        if not isinstance(html_content, str):
            return html_content
        for old, new in replacements:
            html_content = html_content.replace(old, new)
        return html_content

    def blueprint_markdown(text):
        """Convert markdown to HTML, preserving blueprint code blocks with spans intact."""
        logger_md = current_app.logger

        if not text:
            return Markup("")
        local_placeholder_storage = {}
        def replace_blueprint_block(match):
            block_content = match.group(1)
            placeholder_uuid = str(uuid.uuid4())
            placeholder_comment = f""
            local_placeholder_storage[placeholder_comment] = block_content
            return placeholder_comment

        text_with_placeholders = re.sub(
            r'```blueprint\r?\n(.*?)\r?\n```', replace_blueprint_block, text,
            flags=re.DOTALL | re.IGNORECASE
        )

        try:
            html_output_md = markdown.markdown(
                text_with_placeholders,
                extensions=['markdown.extensions.tables', 'markdown.extensions.fenced_code', 'markdown.extensions.nl2br']
            )
        except Exception as e:
            logger_md.error(f"Error during markdown conversion: {e}", exc_info=True)
            return Markup(f"<p>Error during Markdown processing: {html_escape(str(e))}</p>")

        for placeholder, content in local_placeholder_storage.items():
            escaped_content = html_escape(content)
            blueprint_html = f'<pre class="blueprint"><code class="nohighlight blueprint-code" data-nohighlight="true">{Markup(escaped_content)}</code></pre>'
            html_output_md = html_output_md.replace(placeholder, blueprint_html)

        html_output_md = process_blueprint_tables(html_output_md, preserve_params=True)

        allowed_tags = bleach.sanitizer.ALLOWED_TAGS | {
            'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'hr', 'strong', 'em',
            'ul', 'ol', 'li', 'pre', 'code', 'span', 'div', 'a', 'img', 'table',
            'thead', 'tbody', 'tr', 'th', 'td', 'blockquote'
        }
        allowed_attrs = {
            '*': ['class', 'id', 'style', 'data-nohighlight'],
            'a': ['href', 'title', 'id', 'class', 'target'],
            'img': ['src', 'alt', 'title', 'width', 'height'],
            'code': ['class', 'data-nohighlight'],
            'pre': ['class'],
            'span': ['class', 'style'],
            'td': ['colspan', 'rowspan', 'style', 'class'],
            'th': ['colspan', 'rowspan', 'style', 'class'],
            'div': ['class', 'style', 'id']
        }
        try:
            clean_html = bleach.clean(str(html_output_md), tags=allowed_tags, attributes=allowed_attrs, strip=True)
            clean_html = clean_html_entities(clean_html)
        except Exception as e:
            logger_md.error(f"Error during HTML sanitization: {e}", exc_info=True)
            clean_html = f"<p>Error during HTML sanitization: {html_escape(str(e))}</p>"

        return Markup(clean_html)

    # Register the custom Markdown filter
    app.jinja_env.filters['markdown'] = blueprint_markdown

    def process_blueprint_tables(html_content_tbl, preserve_params=True):
        """Process and enhance tables in Blueprint output."""
        logger_tbl = current_app.logger

        table_pattern = r'<table(.*?)>(.*?)</table>'
        def process_table_match(match):
            table_attrs = match.group(1)
            table_content_inner = match.group(2)
            current_classes = ""
            class_attr_match = re.search(r'class=(["\'])(.*?)(\1)', table_attrs, re.IGNORECASE)
            if class_attr_match:
                current_classes = class_attr_match.group(2)
                table_attrs = re.sub(r'\s*class=["\'].*?["\']', '', table_attrs, flags=re.IGNORECASE).strip()

            new_classes_set = {"blueprint-table"}
            if '<th>Function</th>' in table_content_inner and '<th>Target</th>' in table_content_inner:
                new_classes_set.add("function-table")

            final_classes = list(set(current_classes.split()) | new_classes_set)
            if final_classes:
                table_attrs += f' class="{" ".join(final_classes)}"'

            processed_table = f'<table{table_attrs}>{table_content_inner}</table>'
            return processed_table

        if not isinstance(html_content_tbl, str):
            return html_content_tbl

        try:
            processed_html = re.sub(table_pattern, process_table_match, html_content_tbl, flags=re.IGNORECASE | re.DOTALL)
            return processed_html
        except Exception as e:
            logger_tbl.error(f"Error processing blueprint tables: {e}", exc_info=True)
            return html_content_tbl

    # ==============================================================================
    # Main Index Route (GET only now for form display)
    # ==============================================================================
    @app.route('/', methods=['GET'])
    def index():
        logger = current_app.logger
        logger.debug("GET request: Rendering initial page for upload.")
        # Render the template containing the JS for chunked upload
        return render_template('index.html',
                               blueprint_output="",
                               ai_output="",
                               error_message="",
                               raw_blueprint_text=request.args.get('blueprint_text', ''),
                               stats_summary="",
                               task_id=None,
                               task_status=None,
                               processing_message=None)

    # ==============================================================================
    # Task Status Check Route
    # ==============================================================================
    @app.route('/status/<task_id>', methods=['GET'])
    def task_status_check(task_id):
        logger = current_app.logger

        if not celery:
            logger.error("Celery not available for status check.")
            return jsonify({"status": "ERROR", "message": "Celery backend not configured."}), 500

        try:
            logger.debug(f"Checking status for task ID: {task_id}")
            task = celery.AsyncResult(task_id)

            response_data = {
                "task_id": task_id,
                "status": task.state,
                "result": None,
                "error": None
            }

            if task.state == 'SUCCESS':
                task_result_dict = task.result
                if isinstance(task_result_dict, dict):
                    response_data['result'] = task_result_dict
                else:
                    logger.warning(f"Task {task_id} SUCCESS but result is not a dict: {type(task_result_dict)}")
                    response_data['status'] = 'UNEXPECTED_RESULT'
                    response_data['error'] = 'Task completed but result format was unexpected.'
            elif task.state == 'FAILURE':
                task_result_info = task.result
                logger.warning(f"Task {task_id} failed. Raw result/info: {task_result_info}")
                if isinstance(task_result_info, dict) and 'error' in task_result_info:
                    response_data['error'] = task_result_info.get('error', 'Task failed, specific error unknown.')
                elif isinstance(task_result_info, Exception):
                    response_data['error'] = f"Task failed with exception: {str(task_result_info)}"
                else:
                    response_data['error'] = "Task failed during processing. Check server logs."
            elif task.state in ('PENDING', 'STARTED', 'RECEIVED', 'RETRY'):
                response_data['status'] = 'PROCESSING'

            logger.debug(f"Returning status for {task_id}: {response_data['status']}")
            return jsonify(response_data)

        except Exception as e_status:
            logger.error(f"Error checking Celery task status for {task_id}: {e_status}", exc_info=True)
            return jsonify({"status": "ERROR", "message": "Failed to retrieve task status."}), 500

    # ==============================================================================
    # Markdown Rendering Endpoint
    # ==============================================================================
    @app.route('/render', methods=['POST'])
    @csrf.exempt
    def render_markdown_snippet():
        logger = current_app.logger
        markdown_text = request.data.decode('utf-8')

        if not markdown_text:
            logger.warning("/render called with empty data.")
            return "", 200

        try:
            rendered_html_markup = blueprint_markdown(markdown_text)
            return str(rendered_html_markup), 200
        except Exception as e:
            logger.error(f"Error rendering markdown snippet via /render: {e}", exc_info=True)
            return f"<p><strong>Error rendering content:</strong> {html.escape(str(e))}</p>", 500

    # ==============================================================================
    # Health Check Route
    # ==============================================================================
    @app.route('/health')
    def health_check():
        return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()}), 200

    # ==============================================================================
    # Error Handlers
    # ==============================================================================
    if CSRFError and csrf:
        @app.errorhandler(CSRFError)
        def handle_csrf_error_json(e):
            current_app.logger.warning(f"CSRF Error Handler caught: {e} for path {request.path}", exc_info=False)
            return jsonify(status='error', message=f"CSRF validation failed: {e}. Please refresh the page and try again."), 400

    @app.errorhandler(404)
    def page_not_found(e):
        logger = current_app.logger
        logger.warning(f"404 Not Found: {request.path}", exc_info=e)
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
             return jsonify(error='Not Found', message='The requested URL was not found on the server.'), 404
        return render_template('error.html', error_code=404, error_message="Page not found"), 404

    @app.errorhandler(500)
    def server_error(e):
        logger = current_app.logger
        logger.error(f"500 Internal Server Error: {request.path}", exc_info=e)
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
             return jsonify(error='Internal Server Error', message='An internal server error occurred.'), 500
        return render_template('error.html', error_code=500, error_message="Internal server error"), 500

    if werkzeug:
        @app.errorhandler(413)
        @app.errorhandler(werkzeug.exceptions.RequestEntityTooLarge)
        def request_entity_too_large_handler(e):
            logger = current_app.logger
            logger.warning(f"413 Request Entity Too Large (handler): {request.path}", exc_info=False)
            max_size = current_app.config.get('MAX_CONTENT_LENGTH', 50 * 1024 * 1024)
            max_size_mb = max_size // (1024 * 1024) if max_size else 'Unknown'
            error_msg = f"The submitted data is too large. Maximum size: {max_size_mb} MB."

            if request.endpoint == 'index' and request.method == 'POST':
                 return jsonify(status='error', message=error_msg), 413
            if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                 return jsonify(status='error', message=error_msg), 413
            return render_template('error.html', error_code=413, error_message=error_msg), 413
    else:
        @app.errorhandler(413)
        def request_entity_too_large_handler_basic(e):
             logger = current_app.logger
             logger.warning(f"413 Request Entity Too Large (basic handler): {request.path}", exc_info=False)
             max_size = current_app.config.get('MAX_CONTENT_LENGTH', 50 * 1024 * 1024)
             max_size_mb = max_size // (1024 * 1024) if max_size else 'Unknown'
             error_msg = f"The submitted data is too large. Maximum size: {max_size_mb} MB."
             if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                 return jsonify(status='error', message=error_msg), 413
             return render_template('error.html', error_code=413, error_message=error_msg), 413

    @app.errorhandler(Exception)
    def handle_exception(e):
        logger = current_app.logger
        if werkzeug and isinstance(e, werkzeug.exceptions.HTTPException):
            return e

        logger.error(f"Unhandled Exception caught by generic handler: {request.path}", exc_info=True)

        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
            return jsonify(status='error', message='An unexpected server error occurred.'), 500
        return render_template('error.html', error_code=500, error_message="An unexpected error occurred."), 500

