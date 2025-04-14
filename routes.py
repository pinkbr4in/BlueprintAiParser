# routes.py
import sys
import json
import markdown
import bleach
import re         # Keep import re at top
import uuid
import os         # Keep import os
from datetime import datetime
from flask import render_template, request, jsonify, current_app
from markupsafe import Markup
import traceback  # Keep for error logging
from urllib.parse import unquote_plus # Keep import unquote_plus at top

# Assuming these imports are correct
from blueprint_parser.parser import BlueprintParser
from blueprint_parser.formatter.formatter import get_formatter
from blueprint_parser.unsupported_nodes import get_unsupported_graph_type

# Import werkzeug exceptions
try:
    import werkzeug.exceptions
except ImportError:
    werkzeug = None # Set to None if werkzeug not found

# Import CSRF validation components and the shared CSRF object
try:
    from flask_wtf.csrf import validate_csrf, CSRFError
    from app import csrf # <--- Import the shared csrf object from app.py
except ImportError:
    validate_csrf = None
    CSRFError = None
    csrf = None
    # Log a warning or raise a configuration error if CSRF is expected but not installed
    # For now, we'll rely on later checks within the route.
    # Consider adding: current_app.logger.warning("Flask-WTF not installed or CSRF object unavailable. CSRF features disabled.")


def register_routes(app):
    # Helper functions (remain the same)
    def html_escape(text):
        """Escapes text for use in HTML attribute values."""
        if not text:
            return ""
        return text.replace('&', '&amp;').replace('"', '&quot;').replace("'", "&#39;")

    def clean_html_entities(html_content):
        """Normalize HTML entities to prevent double escaping."""
        replacements = [
            ('&amp;lt;', '&lt;'), ('&amp;gt;', '&gt;'), ('&amp;amp;', '&amp;'),
            ('&amp;quot;', '&quot;'), ('&amp;#39;', '&#39;')
        ]
        if not isinstance(html_content, str): # Ensure it's a string
              return html_content
        for old, new in replacements:
            html_content = html_content.replace(old, new)
        return html_content

    def blueprint_markdown(text):
        """Convert markdown to HTML, preserving blueprint code blocks with spans intact."""
        if not text:
            return Markup("")
        local_placeholder_storage = {}
        def replace_blueprint_block(match):
            block_content = match.group(1)
            placeholder_uuid = str(uuid.uuid4())
            # Use a unique HTML comment as placeholder
            placeholder_comment = f"<!-- BP_PLACEHOLDER_{placeholder_uuid} -->"
            local_placeholder_storage[placeholder_comment] = block_content
            return placeholder_comment

        text_with_placeholders = re.sub(
            r'```blueprint\r?\n(.*?)\r?\n```', replace_blueprint_block, text,
            flags=re.DOTALL | re.IGNORECASE
        )
        try:
            html = markdown.markdown(
                text_with_placeholders,
                extensions=['markdown.extensions.tables', 'markdown.extensions.fenced_code', 'markdown.extensions.nl2br']
            )
        except Exception as e:
            current_app.logger.error(f"Error during markdown conversion: {e}", exc_info=True)
            return Markup(f"<p>Error during Markdown processing: {e}</p>")

        # Fix: Move the html.replace() call INSIDE the loop
        for placeholder, content in local_placeholder_storage.items():
            blueprint_html = f'<pre class="blueprint"><code class="nohighlight blueprint-code" data-nohighlight="true">{Markup(content)}</code></pre>'
            html = html.replace(placeholder, blueprint_html)  # This line should be INSIDE the loop

        html = process_blueprint_tables(html, preserve_params=True)
        allowed_tags = bleach.sanitizer.ALLOWED_TAGS | {
            'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'hr', 'strong', 'em',
            'ul', 'ol', 'li', 'pre', 'code', 'span', 'div', 'a', 'img', 'table',
            'thead', 'tbody', 'tr', 'th', 'td', 'blockquote'
        }
        allowed_attrs = {
            '*': ['class', 'id', 'style', 'data-nohighlight'], # Allow common attributes on all
            'a': ['href', 'title', 'id', 'class', 'target'],
            'img': ['src', 'alt', 'title', 'width', 'height'],
            'code': ['class', 'data-nohighlight'], # Ensure class and data-nohighlight are allowed
            'pre': ['class'], # Allow class on pre
            'span': ['class', 'style'], # Allow class and style on span
            'td': ['colspan', 'rowspan', 'style', 'class'],
            'th': ['colspan', 'rowspan', 'style', 'class'],
            'div': ['class', 'style', 'id']
        }
        try:
            clean_html = bleach.clean(str(html), tags=allowed_tags, attributes=allowed_attrs, strip=True)
            clean_html = clean_html_entities(clean_html) # Clean entities after bleach
        except Exception as e:
            current_app.logger.error(f"Error during HTML sanitization: {e}", exc_info=True)
            clean_html = f"<p>Error during HTML sanitization: {e}</p>"
        return Markup(clean_html)


    app.jinja_env.filters['markdown'] = blueprint_markdown

    def process_blueprint_tables(html, preserve_params=True):
        """Process and enhance tables in Blueprint output."""
        # ... (process_blueprint_tables function remains unchanged) ...
        table_pattern = r'<table(.*?)>(.*?)</table>'
        def process_table_match(match):
            table_attrs = match.group(1)
            table_content = match.group(2)
            current_classes = ""
            # Extract existing classes more reliably
            class_attr_match = re.search(r'class=(["\'])(.*?)(\1)', table_attrs, re.IGNORECASE)
            if class_attr_match:
                current_classes = class_attr_match.group(2)
                # Remove the old class attribute to avoid duplication
                table_attrs = re.sub(r'\s*class=["\'].*?["\']', '', table_attrs, flags=re.IGNORECASE).strip()

            # Determine new classes to add
            new_classes_set = {"blueprint-table"} # Start with the base class
            if '<th>Function</th>' in table_content and '<th>Target</th>' in table_content:
                new_classes_set.add("function-table")

            # Combine existing and new classes, ensuring uniqueness
            final_classes = list(set(current_classes.split()) | new_classes_set)

            # Add the final class attribute back
            if final_classes:
                table_attrs += f' class="{" ".join(final_classes)}"'

            processed_table = f'<table{table_attrs}>{table_content}</table>'
            return processed_table

        if not isinstance(html, str):
              return html # Return input if not a string

        processed_html = re.sub(table_pattern, process_table_match, html, flags=re.IGNORECASE | re.DOTALL)
        return processed_html


    # Main route handler
    # --- ADD CSRF EXEMPTION ---
    @csrf.exempt  # <--- Make the route exempt from automatic CSRF checking
    @app.route('/', methods=['GET', 'POST'])
    def index():
        logger = current_app.logger
        output = ""
        ai_output = ""
        error = ""
        stats_summary = ""
        raw_text = "" # Holds the *decoded* blueprint text after manual processing
        human_format_type = "enhanced_markdown" # Moved definitions outside POST block
        ai_format_type = "ai_readable"      # Moved definitions outside POST block

        content_length_header = request.headers.get('Content-Length')
        logger.info(f"Received request: Method={request.method}, Content-Length Header={content_length_header}")

        if request.method == 'POST':
            # Check if CSRF components are available before proceeding with POST
            if not csrf or not validate_csrf or not CSRFError:
                 logger.error("CSRF components (csrf object, validate_csrf, CSRFError) not available. Aborting POST request.")
                 error = "Server configuration error: CSRF validation component missing or disabled."
                 # Render the main template with the error, as it's not a standard HTTP error code situation
                 return render_template('index.html', error_message=error, raw_blueprint_text="", blueprint_output="", ai_output="", stats_summary="")


            # --- NEW: Manual STREAMING Raw Data Processing and CSRF Check ---
            # This replaces the request.get_data() block from the original
            try:
                # Set a reasonable max_size (e.g., use config or fallback)
                # Use a smaller, more realistic default if not set, e.g., 50MB
                max_size = current_app.config.get('MAX_CONTENT_LENGTH', 50 * 1024 * 1024)
                logger.info(f"Using MAX_CONTENT_LENGTH: {max_size} bytes")

                # 1. Check Content-Length Header first
                if content_length_header:
                    try:
                        content_length = int(content_length_header)
                        logger.info(f"Content-Length is {content_length} bytes.")
                        if content_length > max_size:
                            logger.warning(f"Content-Length {content_length} exceeds MAX_CONTENT_LENGTH {max_size}. Returning 413.")
                            return render_template('error.html',
                                                   error_code=413,
                                                   error_message=f"The Blueprint text is too large (based on header). Maximum size: {max_size // (1024 * 1024)} MB."), 413
                    except ValueError:
                        logger.warning(f"Could not parse Content-Length header: {content_length_header}. Proceeding with stream read check.")

                # 2. Read raw data DIRECTLY from request.stream using chunks
                logger.info(f"Attempting to read raw request stream (up to {max_size} bytes)...")
                chunks = []
                total_size = 0
                chunk_size = 8192  # 8KB chunks (adjust as needed)

                stream = request.stream # Get the input stream
                while True:
                    chunk = stream.read(chunk_size)
                    if not chunk:
                        break # End of stream

                    # Check size incrementally to prevent memory issues and enforce limit
                    total_size += len(chunk)
                    if total_size > max_size:
                        logger.warning(f"Stream data exceeds limit after reading {total_size} bytes (limit: {max_size}). Returning 413.")
                        # Consume the rest of the stream to prevent potential connection issues? Optional.
                        # while stream.read(chunk_size): pass
                        return render_template('error.html',
                                               error_code=413,
                                               error_message=f"The Blueprint text is too large (detected during streaming). Maximum size: {max_size // (1024 * 1024)} MB."), 413

                    chunks.append(chunk)
                    # Optional: Log progress for very large uploads if needed
                    # if total_size % (1024 * 1024) == 0: # Log every MB
                    #    logger.debug(f"Read {total_size // (1024 * 1024)} MB so far...")

                # Combine chunks and decode
                raw_data = b''.join(chunks)
                logger.info(f"Successfully read {len(raw_data)} bytes from request stream")

                # 3. Now decode the data
                try:
                    text_data = raw_data.decode('utf-8')
                    logger.debug("Successfully decoded raw data as UTF-8.")
                except UnicodeDecodeError as ude:
                    logger.error(f"Failed to decode raw data as UTF-8: {ude}", exc_info=True)
                    error = "Failed to decode request data. Please ensure it's UTF-8 encoded."
                    return render_template('index.html', error_message=error, raw_blueprint_text="", blueprint_output="", ai_output="", stats_summary="")

                # 4. Parse fields from the *decoded* form data (using regex as before)
                # Parse CSRF token first for security validation
                logger.debug("Searching for CSRF token in decoded text data...")
                csrf_token_match = re.search(r'csrf_token=([^&]+)', text_data)
                if not csrf_token_match:
                    logger.error("CSRF token field not found in request data.")
                    return render_template('error.html',
                                           error_code=400,
                                           error_message="CSRF validation failed (token missing). Please refresh and try again."), 400

                # Unescape the token (important for URL-encoded data)
                csrf_token = unquote_plus(csrf_token_match.group(1))
                logger.debug("Found potential CSRF token field.")

                # 5. Manually validate CSRF token
                try:
                    logger.info("Validating CSRF token manually...")
                    validate_csrf(csrf_token)  # This throws CSRFError if invalid
                    logger.info("CSRF token validation successful.")
                except CSRFError as e_csrf:
                    logger.error(f"CSRF validation failed: {e_csrf}", exc_info=True)
                    return render_template('error.html',
                                           error_code=400,
                                           error_message=f"CSRF validation failed ({e_csrf}). Please refresh and try again."), 400

                # 6. Now extract the blueprint text (after CSRF validation)
                logger.debug("Searching for blueprint_text field...")
                blueprint_text_match = re.search(r'blueprint_text=([^&]+)', text_data)
                if blueprint_text_match:
                    # This handles URL decoding the text
                    raw_text = unquote_plus(blueprint_text_match.group(1)) # Assign to raw_text for later use
                    logger.info(f"Successfully extracted blueprint_text ({len(raw_text)} characters) after CSRF validation.")
                else:
                    logger.warning("No 'blueprint_text' field found in request data after CSRF validation.")
                    error = "Please paste some Blueprint text."
                    # Render main page with error, passing back empty raw_text
                    return render_template('index.html', error_message=error, raw_blueprint_text="", blueprint_output="", ai_output="", stats_summary="")

            # --- Exception Handling specific to STREAMING/Manual Parsing/CSRF ---
            # Note: RequestEntityTooLarge might be caught by the streaming check itself now.
            # Werkzeug might still raise it earlier if MAX_CONTENT_LENGTH is enforced by middleware/server.
            except werkzeug.exceptions.RequestEntityTooLarge as e_large:
                 logger.error(f"CAUGHT RequestEntityTooLarge during manual data processing: {e_large}", exc_info=True)
                 max_mb = max_size // (1024*1024) if max_size else 'Unknown'
                 error_msg = f"Request Entity Too Large. Limit: {max_mb} MB."
                 # Render the specific error template for 413
                 return render_template('error.html', error_code=413, error_message=error_msg), 413
            except Exception as e_manual:
                 # Catch-all for other unexpected errors during the manual stream processing/parsing
                 logger.error(f"Unexpected error during manual request processing/streaming: {e_manual}", exc_info=True)
                 error = f"Error processing request data: {e_manual}. Please check input or contact support."
                 # Render main template with the generic error
                 return render_template('index.html', error_message=error, raw_blueprint_text="", blueprint_output="", ai_output="", stats_summary="")
            # --- End Manual STREAMING Raw Data Processing ---


            # ========== Start Blueprint Parsing/Formatting ==========
            # This block only runs if `raw_text` was successfully extracted above
            # and no errors occurred during the manual processing/CSRF check.
            if not error and raw_text: # Check error is empty AND raw_text has content
                start_time = datetime.now()
                logger.info(f"Processing request started at {start_time}...")
                logger.info(f"Input length OK ({len(raw_text)} chars). Proceeding to parse...") # Note: len(raw_text) is char count now

                # ----- Main PARSING/FORMATTING Block (logic remains the same as original) -----
                detected_unsupported = None
                warning_message = ""
                is_unsupported = False
                try:
                    logger.info("Attempting unsupported type check...")
                    # ***** START OF UNSUPPORTED TYPE CHECK *****
                    try:
                        preliminary_check_lines = raw_text.splitlines()[:20]
                        common_unsupported_hints = [
                            "/Script/UnrealEd.MaterialGraphNode", "/Script/Engine.MaterialExpression",
                            "/Script/AnimGraph.", "/Script/MetasoundEditor.", "/Script/NiagaraEditor.",
                            "/Script/PCGEditor.", "/Script/AIGraph."
                        ]
                        for line in preliminary_check_lines:
                            if 'Class=' in line or 'MaterialExpression' in line or 'GraphNode' in line:
                                class_path = None
                                class_match = re.search(r'Class=(?:ObjectProperty|SoftObjectProperty)?\'?\"?(/[^\"\']+)', line)
                                if class_match:
                                    class_path = class_match.group(1).strip("'\"")
                                else:
                                    for hint in common_unsupported_hints:
                                        if hint in line:
                                            class_path = hint
                                            break
                                if class_path:
                                    unsupported_type = get_unsupported_graph_type(class_path)
                                    if unsupported_type:
                                        detected_unsupported = unsupported_type
                                        is_unsupported = True
                                        logger.debug(f"Detected potential unsupported type: {unsupported_type} from path: {class_path}")
                                        break # Stop checking lines
                        if detected_unsupported:
                            warning_message = f"Warning: Input appears to be an unsupported graph type ({detected_unsupported}). Results may be incomplete or inaccurate."
                            logger.info(f"Unsupported type warning generated: {warning_message}")
                    except ImportError:
                        logger.warning("Could not import 'unsupported_nodes' module for pre-check.", exc_info=True)
                    except Exception as pre_check_err:
                        logger.warning(f"Error during unsupported node pre-check: {pre_check_err}", exc_info=True)
                    # ***** END OF UNSUPPORTED TYPE CHECK *****

                    logger.info("Attempting parser instantiation...")
                    parser = BlueprintParser()

                    logger.info("Attempting parser.parse()...")
                    nodes = parser.parse(raw_text) # Use the decoded raw_text
                    node_count = len(nodes) if nodes else 0
                    comment_count = len(parser.comments) if parser.comments else 0
                    logger.info(f"Parsing finished. Nodes: {node_count}, Comments: {comment_count}")

                    # Handle parsing results
                    if not nodes and not parser.comments and not detected_unsupported:
                        error = "No valid Blueprint nodes or comments found in the input."
                        logger.warning("Parsing resulted in no nodes or comments.")
                    elif nodes or parser.comments:
                        logger.info("Attempting human formatting...")
                        human_formatter = get_formatter(human_format_type, parser)
                        output = human_formatter.format_graph(input_filename="Pasted Blueprint")
                        logger.info("Human formatting finished.")

                        # Debug checks and cleaning (unchanged)
                        if isinstance(output, str) and "<span class=" in output:
                             logger.debug(f"Found {output.count('<span class=')} spans in formatter output")
                        else:
                              logger.warning("NO SPANS found in formatter output or output is not string")
                        output = clean_html_entities(output) # Clean entities before markdown
                        stats_summary = human_formatter.format_statistics()
                        logger.debug("Cleaned HTML entities and got stats summary.")

                        logger.info("Attempting AI formatting...")
                        ai_formatter = get_formatter(ai_format_type, parser)
                        ai_output = ai_formatter.format_graph(input_filename="Pasted Blueprint")
                        logger.info("AI formatting finished.")

                        logger.debug(f"Human output size: {len(str(output))}, AI output size: {len(str(ai_output))}")

                        # Prepend warning if necessary AFTER successful parsing/formatting
                        if is_unsupported and warning_message:
                            logger.info("Prepending unsupported type warning to output.")
                            # Ensure output is treated as a string here
                            output = f"<div class='alert alert-warning'>{html_escape(warning_message)}</div>\n\n" + str(output)
                            # Set error message for display, even if processing succeeded partially
                            error = warning_message # Overwrite previous 'error' if any
                    elif detected_unsupported and warning_message:
                         # Case: Only detected unsupported, no nodes/comments found by parser
                         error = warning_message # Ensure the warning is the main error message
                         logger.warning("Parsing found no nodes/comments, but an unsupported type was detected.")


                # ----- Exception Handling for Parsing/Formatting Block -----
                except ImportError as e_parse_import:
                    logger.error(f"Runtime Import Error during PARSING/FORMATTING block: {e_parse_import}", exc_info=True)
                    error_msg = f"A required module could not be imported during processing: {e_parse_import}."
                    error = f"{error}\n{error_msg}".strip() if error else error_msg # Append if warning exists
                except Exception as e_parse:
                    logger.error(f"EXCEPTION during PARSING/FORMATTING block: {e_parse}", exc_info=True)
                    error_msg = f"An error occurred during processing: {e_parse}. Check logs."
                    error = f"{error}\n{error_msg}".strip() if error else error_msg # Append if warning exists
                # ----- End Main Parsing/Formatting Block -----

                end_time = datetime.now()
                duration = end_time - start_time
                logger.info(f"Finished processing block. Duration: {duration}. Error status: '{error}'")
            # ========== End Blueprint Parsing/Formatting ==========

        # --- GET request handling (remains the same) ---
        elif request.method == 'GET':
            # Handle GET request (e.g., initial page load)
            # Potentially pre-fill from query params if needed, but raw_text is mainly for POST result
            raw_text_get = request.args.get('blueprint_text', '') # Use a different var name if needed
            if raw_text_get:
                 logger.debug("Received blueprint_text via GET request, but not processing.")
                 # Decide if you want to display this GET param in the textarea
                 # raw_text = raw_text_get # Uncomment to display GET param in textarea on load
        # --- End GET request handling ---

        # --- Render final template (for GET requests or successful/failed POST) ---
        # This is reached for GET requests, or after the POST processing (manual + parsing) is complete.
        # The 'error' variable will contain any messages generated during POST.
        logger.debug(f"Preparing to render template. Final Error message: '{error}'")
        # Make sure raw_text passed is the one potentially processed, or empty for GET
        return render_template('index.html',
                               blueprint_output=output, # Contains formatted HTML or ""
                               ai_output=ai_output,     # Contains AI formatted text or ""
                               error_message=error,     # Contains error string or ""
                               raw_blueprint_text=raw_text, # Pass back the processed raw text (or "" for GET/initial POST)
                               stats_summary=stats_summary) # Contains stats or ""


    # --- Health Check Endpoint (remains the same) ---
    @app.route('/health')
    def health_check():
        return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()}), 200

    # --- Error Handlers (remain largely the same) ---
    # Note: The direct returns in the POST handler for 400/413 bypass these handlers for those specific cases.
    @app.errorhandler(404)
    def page_not_found(e):
        current_app.logger.warning(f"404 Not Found: {request.path}", exc_info=e)
        return render_template('error.html', error_code=404, error_message="Page not found"), 404

    @app.errorhandler(500)
    def server_error(e):
        # Avoid logging errors handled by specific handlers if possible
        # Check if the original exception was one we handle specifically
        original_exception = getattr(e, 'original_exception', None)
        if CSRFError and isinstance(original_exception, CSRFError):
             # Already handled by CSRFError handler (if registered) or manually
             # We might still end up here if the CSRFError handler itself fails
             current_app.logger.warning(f"Reached 500 handler for a CSRFError: {request.path}", exc_info=e)
        elif werkzeug and isinstance(original_exception, werkzeug.exceptions.RequestEntityTooLarge):
             # Already handled by 413 handler or manually
             current_app.logger.warning(f"Reached 500 handler for a RequestEntityTooLarge: {request.path}", exc_info=e)
        else:
             current_app.logger.error(f"500 Internal Server Error: {request.path}", exc_info=e)

        return render_template('error.html', error_code=500, error_message="Internal server error"), 500

    @app.errorhandler(413)
    def request_entity_too_large_handler(e):
        current_app.logger.warning(f"413 Request Entity Too Large (handler): {request.path}", exc_info=e)
        # Try to get configured max_size, default if not set or 0
        max_size = current_app.config.get('MAX_CONTENT_LENGTH', 0)
        # Use the same default as in the index route if config is missing/0
        if not max_size: max_size = 50 * 1024 * 1024
        max_size_mb = max_size // (1024 * 1024)
        error_msg = f"The Blueprint text is too large to process. Maximum size: {max_size_mb} MB."
        return render_template('error.html', error_code=413, error_message=error_msg), 413

    # Catch CSRFErrors globally too, as a fallback
    if CSRFError: # Only register if CSRFError could be imported
        @app.errorhandler(CSRFError)
        def handle_csrf_error(e):
            logger.warning(f"Global CSRF Error Handler caught: {e} for path {request.path}", exc_info=True)
            return render_template('error.html',
                                   error_code=400,
                                   error_message=f"CSRF validation failed: {e}. Please refresh and try again."), 400


    # Generic Exception handler (use carefully, might catch things unexpectedly)
    @app.errorhandler(Exception)
    def handle_exception(e):
        # Check if it's an HTTPException that Werkzeug/Flask might handle
        if werkzeug and isinstance(e, werkzeug.exceptions.HTTPException):
            # Let specific handlers take precedence if they exist
            if isinstance(e, werkzeug.exceptions.NotFound): return page_not_found(e)
            if isinstance(e, werkzeug.exceptions.RequestEntityTooLarge): return request_entity_too_large_handler(e)
            # If it's a CSRF error, let that handler deal with it
            if CSRFError and isinstance(e, CSRFError): return handle_csrf_error(e)
            # Otherwise, let Flask's default handling for HTTPExceptions proceed
            return e

        # Handle non-HTTP exceptions or those without specific handlers
        # Check for CSRF error again in case the direct @app.errorhandler(CSRFError) wasn't hit
        if CSRFError and isinstance(e, CSRFError):
            return handle_csrf_error(e) # Delegate to the specific CSRF handler

        # Log all other unexpected errors
        current_app.logger.error(f"Unhandled Exception caught by generic handler: {request.path}", exc_info=e)
        return render_template('error.html', error_code=500, error_message="An unexpected error occurred."), 500

# --- End of register_routes function ---