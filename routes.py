# routes.py
import sys
import json
import markdown
import bleach
import re
import uuid
import os # Keep import os
from datetime import datetime
from flask import render_template, request, jsonify, current_app
from markupsafe import Markup
import traceback # Keep for error logging

# Assuming these imports are correct
from blueprint_parser.parser import BlueprintParser
from blueprint_parser.formatter.formatter import get_formatter
from blueprint_parser.unsupported_nodes import get_unsupported_graph_type

# Import werkzeug exceptions and potentially LimitedStream
try:
    import werkzeug.exceptions
    from werkzeug.wsgi import LimitedStream # <-- Import LimitedStream
except ImportError:
    werkzeug = None
    LimitedStream = None # Set to None if werkzeug not found


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
            placeholder_comment = f""
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

        for placeholder, content in local_placeholder_storage.items():
            blueprint_html = f'<pre class="blueprint"><code class="nohighlight blueprint-code" data-nohighlight="true">{Markup(content)}</code></pre>'
            html = html.replace(placeholder, blueprint_html)

        html = process_blueprint_tables(html, preserve_params=True)
        allowed_tags = bleach.sanitizer.ALLOWED_TAGS | {
            'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'hr', 'strong', 'em',
            'ul', 'ol', 'li', 'pre', 'code', 'span', 'div', 'a', 'img', 'table',
            'thead', 'tbody', 'tr', 'th', 'td', 'blockquote'
        }
        allowed_attrs = {
            '*': ['class', 'id', 'style', 'data-nohighlight'],
            'a': ['href', 'title', 'id', 'class', 'target'],
            'img': ['src', 'alt', 'title', 'width', 'height'],
            'code': ['class', 'data-nohighlight'], 'pre': ['class'],
            'span': ['class', 'style'],
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
        table_pattern = r'<table(.*?)>(.*?)</table>'
        def process_table_match(match):
            table_attrs = match.group(1)
            table_content = match.group(2)
            current_classes = ""
            if 'class=' in table_attrs:
                class_match = re.search(r'class=(["\'])(.*?)(\1)', table_attrs, re.IGNORECASE)
                if class_match:
                    current_classes = class_match.group(2)
                    table_attrs = re.sub(r'\s*class=["\'].*?["\']', '', table_attrs, flags=re.IGNORECASE)

            new_classes = "blueprint-table"
            if '<th>Function</th>' in table_content and '<th>Target</th>' in table_content:
                new_classes += " function-table"

            final_classes = list(set(current_classes.split() + new_classes.split()))
            table_attrs += f' class="{" ".join(final_classes)}"'
            processed_table = f'<table{table_attrs}>{table_content}</table>'
            return processed_table
        if not isinstance(html, str):
             return html
        processed_html = re.sub(table_pattern, process_table_match, html, flags=re.IGNORECASE | re.DOTALL)
        return processed_html

    # Main route handler
    @app.route('/', methods=['GET', 'POST'])
    def index():
        logger = current_app.logger

        output = ""
        ai_output = ""
        error = ""
        stats_summary = ""
        raw_text = ""
        human_format_type = "enhanced_markdown"
        ai_format_type = "ai_readable"

        content_length_header = request.headers.get('Content-Length')
        logger.info(f"Received request: Method={request.method}, Content-Length Header={content_length_header}")

        # --- MODIFIED POST HANDLING ---
        if request.method == 'POST':
            max_size = current_app.config.get('MAX_CONTENT_LENGTH')
            if max_size is None:
                logger.warning("MAX_CONTENT_LENGTH not set in config, using default 500MB.")
                max_size = 500 * 1024 * 1024 # Default to 500MB if not set

            try:
                # Check Content-Length header BEFORE trying to read data
                content_length = 0
                if content_length_header:
                    try:
                        content_length = int(content_length_header)
                        logger.info(f"Content-Length is {content_length} bytes.")
                        if content_length > max_size:
                            logger.warning(f"Content-Length {content_length} exceeds MAX_CONTENT_LENGTH {max_size}. Raising RequestEntityTooLarge.")
                            # Raise the specific exception Flask/Werkzeug expects
                            if werkzeug: # Check if werkzeug is available
                                raise werkzeug.exceptions.RequestEntityTooLarge(
                                    f"Request content length {content_length} exceeds configured MAX_CONTENT_LENGTH {max_size}"
                                )
                            else:
                                # Fallback if werkzeug isn't loaded but we detected the issue
                                raise ValueError(f"Request content length {content_length} exceeds limit {max_size} (Werkzeug not loaded)")

                    except ValueError as ve:
                         # Handle case where Content-Length is not an integer or our fallback ValueError above
                        logger.warning(f"Could not parse Content-Length header or size check failed: {ve}")
                        # If the error was our fallback, re-raise specifically as RequestEntityTooLarge if possible
                        if "exceeds limit" in str(ve) and werkzeug:
                            raise werkzeug.exceptions.RequestEntityTooLarge(str(ve))
                        # Otherwise, proceed cautiously, Werkzeug might catch it later

                    # Note: We don't re-raise RequestEntityTooLarge here because if it was raised above,
                    # it will be caught by the outer except block.

                # Try reading from form first, then fall back to raw data
                logger.info("Attempting to read 'blueprint_text' from request.form first...")
                # This access might still trigger Werkzeug's internal limits before our check
                form_raw_text = request.form.get('blueprint_text')

                if form_raw_text is not None: # If we got it via form, use it
                    raw_text = form_raw_text
                    logger.info(f"Successfully read 'blueprint_text' from request.form. Length: {len(raw_text)} bytes.")
                    # Double-check size again in case Werkzeug parsed it despite header? (optional paranoia)
                    if len(raw_text.encode('utf-8')) > max_size:
                         logger.warning(f"Form data length {len(raw_text.encode('utf-8'))} seems to exceed MAX_CONTENT_LENGTH {max_size} despite passing initial check.")
                         if werkzeug:
                              raise werkzeug.exceptions.RequestEntityTooLarge("Form data exceeds size limit after parsing.")
                         else:
                              raise ValueError("Form data exceeds size limit after parsing (Werkzeug not loaded)")
                else:
                    # Fallback: If request.form didn't contain it or failed silently?
                    logger.warning("'blueprint_text' not found in request.form or form parsing failed, attempting to read raw request data...")
                    # Use request.get_data() which respects MAX_CONTENT_LENGTH set in Flask config
                    # It will raise RequestEntityTooLarge internally if needed.
                    raw_data = request.get_data(cache=False, as_text=True) # Read as text
                    raw_text = raw_data # Assume raw data is the blueprint text
                    logger.info(f"Read raw request data. Length: {len(raw_text)} bytes.")
                    # Optional check: Does raw data look like form data?
                    if raw_text and not raw_text.lstrip().startswith("Begin Object"): # Basic check if it looks like a BP, not raw form data
                        if 'blueprint_text=' in raw_text[:100]: # Check beginning if it looks like form data
                             logger.warning("Raw data looks like form data ('blueprint_text=' found). Did form parsing fail?")
                             # Attempt to extract if it looks like URL-encoded form data
                             match = re.search(r"blueprint_text=([^&]+)", raw_text)
                             if match:
                                 from urllib.parse import unquote_plus
                                 logger.info("Attempting to URL-decode the raw data for 'blueprint_text'.")
                                 raw_text = unquote_plus(match.group(1)) # Decode URL encoding
                                 logger.info(f"Extracted and decoded text length: {len(raw_text)}")
                             else:
                                 logger.warning("Could not extract 'blueprint_text' from raw form-like data.")
                                 # Decide: error out or proceed with raw_text as is? Let's proceed for now.
                        # else: If it doesn't start like a blueprint and doesn't contain blueprint_text=, treat it as raw BP text.

                # --- Final check after attempting retrieval ---
                if not raw_text:
                    # If we reach here with no text and no error was raised yet, set the specific error.
                    error = "Please paste some Blueprint text."
                    logger.warning("Empty blueprint_text received (after trying form and raw data).")

            # --- Exception Handling for Data Retrieval ---
            except werkzeug.exceptions.RequestEntityTooLarge as e_large:
                 if werkzeug: # Check again, just in case
                     logger.error(f"CAUGHT RequestEntityTooLarge during data retrieval: {e_large}", exc_info=True)
                     max_mb = max_size // (1024*1024)
                     # Use a clear, consistent error message
                     error = f"Request Entity Too Large. Limit: {max_mb} MB."
                 else:
                     logger.error(f"Caught RequestEntityTooLarge-like error but Werkzeug not loaded: {e_large}", exc_info=True)
                     error = f"Request Entity Too Large (Limit: {max_size // (1024*1024)} MB). Error: {e_large}"
                 raw_text = "" # Ensure raw_text is empty

            except Exception as e:
                logger.error(f"Failed processing request data: {e}", exc_info=True)
                # Check if it smells like a size error even if not caught specifically
                e_str = str(e).lower()
                if "too large" in e_str or "memory limit" in e_str:
                     max_mb = max_size // (1024*1024)
                     error = f"Likely Limit Hit! Request Entity Too Large? Limit: {max_mb} MB. Error: {e}"
                else:
                     error = f"Failed to read input data: {e}"
                raw_text = ""
            # --- End Data Retrieval Block ---

            logger.info(f"After data retrieval attempt: Error='{error}', Raw text length='{len(raw_text)}'")

            # Only proceed to PARSING if no error AND we actually got text
            if not error and raw_text:
                start_time = datetime.now()
                logger.info(f"Processing request started at {start_time}...")
                logger.info(f"Input length OK ({len(raw_text)} bytes). Proceeding to parse...")

                # ----- Main PARSING/FORMATTING Block (remains the same as previous version) -----
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
                    nodes = parser.parse(raw_text)
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

                        if isinstance(output, str) and "<span class=" in output:
                            logger.debug(f"Found {output.count('<span class=')} spans in formatter output")
                        else:
                            logger.warning("NO SPANS found in formatter output or output is not string")
                        output = clean_html_entities(output)
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
                            output = f"<div class='alert alert-warning'>{warning_message}</div>\n\n" + str(output)
                            # Set error message for display, even if processing succeeded partially
                            error = warning_message

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

            elif error:
                # This case handles errors detected during the initial data retrieval
                logger.warning(f"Processing skipped due to error detected during data retrieval: {error}")
            # ----- End POST request processing -----

        # --- GET request handling (remains the same) ---
        elif request.method == 'GET':
            raw_text = request.args.get('blueprint_text', '')
            if raw_text:
                logger.debug("Received blueprint_text via GET request.")
        # --- End GET request handling ---

        # --- Render final template ---
        logger.debug(f"Preparing to render template. Error message to template: '{error}'")
        return render_template('index.html',
                               blueprint_output=output,
                               ai_output=ai_output,
                               error_message=error,
                               raw_blueprint_text=raw_text, # Pass back raw text even if processing failed
                               stats_summary=stats_summary)

    # --- Health Check Endpoint (remains the same) ---
    @app.route('/health')
    def health_check():
        return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()}), 200

    # --- Error Handlers (remain the same) ---
    @app.errorhandler(404)
    def page_not_found(e):
        current_app.logger.warning(f"404 Not Found: {request.path}", exc_info=e)
        return render_template('error.html', error_code=404, error_message="Page not found"), 404

    @app.errorhandler(500)
    def server_error(e):
        current_app.logger.error(f"500 Internal Server Error: {request.path}", exc_info=e)
        return render_template('error.html', error_code=500, error_message="Internal server error"), 500

    @app.errorhandler(413)
    def request_entity_too_large_handler(e):
        current_app.logger.warning(f"413 Request Entity Too Large: {request.path}", exc_info=e)
        # Try to get configured max_size, default if not set or 0
        max_size = current_app.config.get('MAX_CONTENT_LENGTH', 0)
        if not max_size: max_size = 500 * 1024 * 1024 # Use same default as in index route
        max_size_mb = max_size // (1024 * 1024)
        error_msg = f"The Blueprint text is too large to process. Maximum size: {max_size_mb} MB."
        return render_template('error.html', error_code=413, error_message=error_msg), 413

    @app.errorhandler(Exception)
    def handle_exception(e):
        if werkzeug:
             if isinstance(e, werkzeug.exceptions.NotFound):
                 return page_not_found(e)
             if isinstance(e, werkzeug.exceptions.RequestEntityTooLarge):
                 return request_entity_too_large_handler(e)
             if isinstance(e, werkzeug.exceptions.HTTPException):
                 return e # Let Flask handle other standard HTTP exceptions

        # Handle non-HTTP exceptions or those without specific handlers
        current_app.logger.error(f"Unhandled Exception: {request.path}", exc_info=e)
        return render_template('error.html', error_code=500, error_message="An unexpected error occurred."), 500

# --- End of register_routes function ---