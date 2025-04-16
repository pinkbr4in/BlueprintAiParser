# routes.py
# --- Reverted to using rendering_utils.py for Markdown ---

import sys
import json
# import markdown # No longer needed here
# import bleach   # No longer needed here
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
    from app import csrf # Assuming csrf is initialized in app.py
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

# --- Import Rendering Utils --- ### USE THIS IMPORT ###
try:
    # Import the specific function needed from rendering_utils
    from rendering_utils import blueprint_markdown
    RENDERING_UTILS_AVAILABLE = True
    print("INFO (routes.py): Successfully imported blueprint_markdown from rendering_utils.")
except ImportError as e_render_routes:
     print(f"ERROR (routes.py): Failed to import rendering_utils: {e_render_routes}")
     RENDERING_UTILS_AVAILABLE = False
     # Define a dummy if needed, although errors should ideally be caught later
     def blueprint_markdown(text, logger): return Markup(f"<p>Rendering Error (Import Failed): {html.escape(str(text))}</p>") # Return Markup

# ==============================================================================
# Main Function to Register Routes
# ==============================================================================
def register_routes(app):

    # --- REMOVED Local Helper functions ---
    # --- REMOVED Jinja Filter ---

    # ==============================================================================
    # Main Index Route
    # ==============================================================================
    @app.route('/', methods=['GET'])
    def index():
        logger = current_app.logger
        logger.debug("GET request: Rendering initial page for upload.")
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
    # Task Status Check Route - USING IMPORTED RENDERER
    # ==============================================================================
    @app.route('/status/<task_id>', methods=['GET'])
    def task_status_check(task_id):
        logger = current_app.logger # Get logger for rendering function

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
            processed_status = task.state

            if task.state == 'SUCCESS' or task.state == 'PARTIAL_FAILURE':
                task_result_dict = task.result
                if isinstance(task_result_dict, dict):
                    logger.debug(f"Task {task_id} result dictionary received: Keys={list(task_result_dict.keys())}")

                    rendered_output = ""
                    rendered_stats = ""
                    task_error = task_result_dict.get('error', '')

                    if RENDERING_UTILS_AVAILABLE:
                        try:
                            raw_md = task_result_dict.get('output_markdown', '')
                            raw_stats = task_result_dict.get('stats_markdown', '')
                            logger.debug(f"Rendering output_markdown (len: {len(raw_md)}) and stats_markdown (len: {len(raw_stats)}) using rendering_utils...")

                            # *** Call the IMPORTED blueprint_markdown function ***
                            # It requires the logger instance as the second argument
                            rendered_output_markup = blueprint_markdown(raw_md, logger)
                            rendered_stats_markup = blueprint_markdown(raw_stats, logger)

                            rendered_output = str(rendered_output_markup)
                            rendered_stats = str(rendered_stats_markup)
                            logger.debug("Markdown rendering complete in route using rendering_utils.")

                        except Exception as render_err:
                             logger.error(f"Error rendering markdown in status route using rendering_utils for task {task_id}: {render_err}", exc_info=True)
                             rendered_output = f"<p><strong>Error rendering content:</strong> {html.escape(str(render_err))}</p>"
                             rendered_stats = f"<p><strong>Error rendering stats:</strong> {html.escape(str(render_err))}</p>"
                             response_data['error'] = f"Content rendering failed: {html.escape(str(render_err))}"
                    else:
                         logger.error(f"Rendering utils not available for task {task_id}.")
                         rendered_output = "<p><strong>Server Error:</strong> Rendering utilities unavailable.</p>"
                         rendered_stats = ""
                         response_data['error'] = "Rendering utilities unavailable."

                    frontend_result = {
                        'output': rendered_output,
                        'stats_summary': rendered_stats,
                        'ai_output': task_result_dict.get('ai_output', ''),
                        'error': task_error
                    }
                    response_data['result'] = frontend_result
                    processed_status = task_result_dict.get('status', task.state)

                else:
                    logger.warning(f"Task {task_id} {task.state} but result is not a dict: {type(task_result_dict)}")
                    processed_status = 'UNEXPECTED_RESULT'
                    response_data['error'] = 'Task completed but result format was unexpected.'

            elif task.state == 'FAILURE':
                task_result_info = task.result
                logger.warning(f"Task {task_id} failed. Raw result/info: {task_result_info}")
                if isinstance(task_result_info, dict) and 'error' in task_result_info:
                     response_data['error'] = task_result_info.get('error', 'Task failed, specific error unknown.')
                elif isinstance(task_result_info, Exception):
                     response_data['error'] = f"Task failed with exception: {html.escape(str(task_result_info))}"
                else:
                     response_data['error'] = "Task failed during processing. Check server logs for details."
                processed_status = 'FAILURE'

            elif task.state in ('PENDING', 'STARTED', 'RECEIVED', 'RETRY'):
                processed_status = 'PROCESSING'

            else:
                 processed_status = task.state
                 logger.warning(f"Task {task_id} has unknown state: {task.state}")


            response_data['status'] = processed_status
            logger.debug(f"Returning status for {task_id}: {response_data['status']} (Result keys: {list(response_data.get('result', {}).keys()) if response_data.get('result') else 'None'})")
            return jsonify(response_data)

        except Exception as e_status:
            logger.error(f"Error checking Celery task status for {task_id}: {e_status}", exc_info=True)
            return jsonify({"status": "ERROR", "message": "Failed to retrieve task status."}), 500

    # ==============================================================================
    # Health Check Route
    # ==============================================================================
    @app.route('/health')
    def health_check():
        return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()}), 200

    # ==============================================================================
    # Error Handlers
    # ==============================================================================
    # ... (Keep existing error handlers: CSRF, 404, 500, 413, Exception) ...
    # (Error handler code omitted for brevity, assume it's the same as previous correct version)
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
        original_exception = getattr(e, 'original_exception', e)
        logger.error(f"500 Internal Server Error: {request.path}", exc_info=original_exception)
        if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
             return jsonify(error='Internal Server Error', message='An internal server error occurred.'), 500
        return render_template('error.html', error_code=500, error_message="Internal server error"), 500

    if werkzeug:
        @app.errorhandler(413)
        @app.errorhandler(werkzeug.exceptions.RequestEntityTooLarge)
        def handle_request_entity_too_large(e):
            logger = current_app.logger
            logger.warning(f"413 Request Entity Too Large: {request.path}", exc_info=False)
            max_size = current_app.config.get('MAX_CONTENT_LENGTH', 500 * 1024 * 1024)
            max_size_mb = max_size // (1024 * 1024) if max_size else 'Unknown'
            error_msg = f"The submitted data is too large. Maximum size: {max_size_mb} MB."
            if request.endpoint and 'upload_chunk' in request.endpoint:
                 return jsonify(status='error', message=error_msg), 413
            if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html:
                 return jsonify(status='error', message=error_msg), 413
            return render_template('error.html', error_code=413, error_message=error_msg), 413
    else:
        @app.errorhandler(413)
        def handle_request_entity_too_large_basic(e):
             logger = current_app.logger
             logger.warning(f"413 Request Entity Too Large (basic handler): {request.path}", exc_info=False)
             max_size = current_app.config.get('MAX_CONTENT_LENGTH', 500 * 1024 * 1024)
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


# --- END register_routes ---