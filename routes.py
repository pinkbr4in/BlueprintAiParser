# routes.py
import sys
import json
import markdown
import bleach
import re
import uuid
from datetime import datetime
from flask import render_template, request, jsonify, current_app # Import current_app to access logger easily
from markupsafe import Markup
# Remove unused import if desired, or leave it
# from urllib.parse import unquote_plus
import traceback # Keep for error logging

# Assuming these are correctly importable from the project structure
from blueprint_parser.parser import BlueprintParser
from blueprint_parser.formatter.formatter import get_formatter
from blueprint_parser.unsupported_nodes import get_unsupported_graph_type

# Import werkzeug exceptions for the general error handler
try:
    import werkzeug.exceptions
except ImportError:
    werkzeug = None # Set to None if not available

def register_routes(app):
    # Helper functions (assuming these are correctly defined here)
    # Note: It might be cleaner to move these to a separate 'utils.py' or similar
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
            # Use a unique HTML comment instead of an empty string
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

        for placeholder, content in local_placeholder_storage.items():
            # Use Markup to ensure spans within content are treated as HTML
            # This line already correctly uses Markup() as per the "Additional Improvement" note.
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
            # Ensure html is string before cleaning
            clean_html = bleach.clean(str(html), tags=allowed_tags, attributes=allowed_attrs, strip=True)
            clean_html = clean_html_entities(clean_html) # Clean entities after bleach
        except Exception as e:
            current_app.logger.error(f"Error during HTML sanitization: {e}", exc_info=True)
            clean_html = f"<p>Error during HTML sanitization: {e}</p>"
        # Return as Markup object for Jinja2
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
                    # Remove existing class attribute to rebuild cleanly
                    table_attrs = re.sub(r'\s*class=["\'].*?["\']', '', table_attrs, flags=re.IGNORECASE)

            new_classes = "blueprint-table"
            if '<th>Function</th>' in table_content and '<th>Target</th>' in table_content:
                new_classes += " function-table"

            # Combine existing classes (if any) with new ones, avoiding duplicates
            final_classes = list(set(current_classes.split() + new_classes.split()))
            table_attrs += f' class="{" ".join(final_classes)}"'

            processed_table = f'<table{table_attrs}>{table_content}</table>'
            return processed_table
        # Ensure html is a string before processing
        if not isinstance(html, str):
             return html
        processed_html = re.sub(table_pattern, process_table_match, html, flags=re.IGNORECASE | re.DOTALL)
        return processed_html

    # Main route handler
    @app.route('/', methods=['GET', 'POST'])
    def index():
        # Use current_app.logger which is configured in the app factory
        logger = current_app.logger

        output = ""
        ai_output = ""
        error = ""
        stats_summary = ""
        raw_text = "" # Initialize raw_text

        human_format_type = "enhanced_markdown"
        ai_format_type = "ai_readable"

        if request.method == 'POST':
            try:
                # Standard form handling
                raw_text = request.form.get('blueprint_text', '')
                logger.debug(f"Received blueprint_text with length: {len(raw_text)}")

                if not raw_text:
                    error = "Please paste some Blueprint text."
                    logger.warning("Empty blueprint_text received.")
            except Exception as e:
                logger.error(f"Failed to process form data: {e}", exc_info=True)
                e_str = str(e).lower()
                if "413" in e_str or "request entity too large" in e_str:
                     max_mb = current_app.config.get('MAX_CONTENT_LENGTH', 0) // (1024*1024)
                     error = f"Request Entity Too Large. Max size: {max_mb} MB." if max_mb > 0 else "Request Entity Too Large."
                else:
                     error = f"Failed to read input data: {e}"
                raw_text = ""  # Ensure raw_text is empty on error

            # If we have text and no error was set during form reading, proceed.
            if not error and raw_text:
                start_time = datetime.now()
                logger.info(f"Processing request started at {start_time}...")
                detected_unsupported = None
                warning_message = ""
                is_unsupported = False

                # ----- Main Processing Block -----
                try:
                    # --- Add logs before each major step ---
                    logger.info("Attempting unsupported type check...") # <<< ADDED LOG
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
                            error = warning_message # Set error initially
                            logger.info(f"Unsupported type warning set: {warning_message}")

                    except ImportError:
                        logger.warning("Could not import 'unsupported_nodes' module for pre-check.", exc_info=True)
                    except Exception as pre_check_err:
                        logger.warning(f"Error during unsupported node pre-check: {pre_check_err}", exc_info=True)
                    # ***** END OF UNSUPPORTED TYPE CHECK *****

                    logger.info("Attempting parser instantiation...") # <<< ADDED LOG
                    parser = BlueprintParser()

                    logger.info("Attempting parser.parse()...") # <<< ADDED LOG
                    nodes = parser.parse(raw_text)
                    # Log results immediately after parsing
                    node_count = len(nodes) if nodes else 0
                    comment_count = len(parser.comments) if parser.comments else 0
                    logger.info(f"Parsing finished. Nodes: {node_count}, Comments: {comment_count}") # <<< ADDED LOG

                    # Handle parsing results
                    if not nodes and not parser.comments and not detected_unsupported:
                        error = "No valid Blueprint nodes or comments found in the input."
                        logger.warning("Parsing resulted in no nodes or comments.")
                    elif nodes or parser.comments:
                        # Proceed with formatting if nodes or comments exist
                        logger.info("Attempting human formatting...") # <<< ADDED LOG
                        human_formatter = get_formatter(human_format_type, parser)
                        output = human_formatter.format_graph(input_filename="Pasted Blueprint")
                        logger.info("Human formatting finished.") # <<< ADDED LOG

                        # Debug checks and cleaning
                        if isinstance(output, str) and "<span class=" in output:
                            logger.debug(f"Found {output.count('<span class=')} spans in formatter output")
                        else:
                            logger.warning("NO SPANS found in formatter output or output is not string")
                        output = clean_html_entities(output)
                        stats_summary = human_formatter.format_statistics()
                        logger.debug("Cleaned HTML entities and got stats summary.")

                        logger.info("Attempting AI formatting...") # <<< ADDED LOG
                        ai_formatter = get_formatter(ai_format_type, parser)
                        ai_output = ai_formatter.format_graph(input_filename="Pasted Blueprint")
                        logger.info("AI formatting finished.") # <<< ADDED LOG

                        logger.debug(f"Human output size: {len(str(output))}, AI output size: {len(str(ai_output))}")

                        # Prepend warning if necessary
                        if is_unsupported and warning_message:
                            logger.info("Prepending unsupported type warning to output.")
                            output = f"<div class='alert alert-warning'>{warning_message}</div>\n\n" + str(output)
                            # Ensure the warning message persists as the primary error if parsing succeeded otherwise
                            error = warning_message
                    # else: case where no nodes/comments but warning exists is implicitly handled

                # ----- Exception Handling for Main Processing Block -----
                except ImportError as e:
                     logger.error(f"Runtime Import Error during parsing/formatting: {e}", exc_info=True)
                     error_msg = f"A required module could not be imported during processing: {e}."
                     error = f"{error}\n{error_msg}".strip() if error else error_msg
                except Exception as e:
                     logger.error(f"An unexpected error occurred during processing: {e}", exc_info=True)
                     error_msg = f"An unexpected error occurred during processing: {e}. Check logs."
                     error = f"{error}\n{error_msg}".strip() if error else error_msg
                # ----- End Main Processing Block -----

                end_time = datetime.now()
                duration = end_time - start_time
                logger.info(f"Processing finished at {end_time}. Duration: {duration}") # <<< ADDED LOG

            # ----- Handle cases where form read failed or text was initially empty -----
            elif not raw_text and not error:
                 error = "Please paste some Blueprint text." # Should be caught by initial check, but as fallback
                 logger.warning("Processing skipped: No blueprint text provided and no prior error.")
            elif error:
                 logger.warning(f"Processing skipped due to initial error: {error}")
            # ----- End POST request processing -----

        # --- GET request handling ---
        elif request.method == 'GET':
            raw_text = request.args.get('blueprint_text', '')
            if raw_text:
                logger.debug("Received blueprint_text via GET request.")
        # --- End GET request handling ---

        # --- Render final template ---
        logger.debug("Rendering index.html template.")
        return render_template('index.html',
                               blueprint_output=output,
                               ai_output=ai_output,
                               error_message=error,
                               raw_blueprint_text=raw_text,
                               stats_summary=stats_summary)

    # --- Health Check Endpoint ---
    @app.route('/health')
    def health_check():
        # Simple health check endpoint
        return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()}), 200

    # --- Error Handlers ---
    # (Error handlers remain the same as previous version - checking werkzeug availability)
    @app.errorhandler(404)
    def page_not_found(e):
        # Use current_app's logger
        current_app.logger.warning(f"404 Not Found: {request.path}", exc_info=e)
        return render_template('error.html', error_code=404, error_message="Page not found"), 404

    @app.errorhandler(500)
    def server_error(e):
        # Use current_app's logger
        current_app.logger.error(f"500 Internal Server Error: {request.path}", exc_info=e)
        return render_template('error.html', error_code=500, error_message="Internal server error"), 500

    @app.errorhandler(413)
    def request_entity_too_large(e):
        # Use current_app's logger
        current_app.logger.warning(f"413 Request Entity Too Large: {request.path}", exc_info=e)
        max_size_mb = current_app.config.get('MAX_CONTENT_LENGTH', 0) // (1024 * 1024)
        error_msg = f"The Blueprint text is too large to process. Maximum size: {max_size_mb} MB." if max_size_mb > 0 else "The Blueprint text is too large to process."
        return render_template('error.html', error_code=413, error_message=error_msg), 413

    @app.errorhandler(Exception)
    def handle_exception(e):
        # Pass through HTTP exceptions handled by specific handlers
        if werkzeug and isinstance(e, (werkzeug.exceptions.NotFound, werkzeug.exceptions.RequestEntityTooLarge)):
             # Reraise the original HTTP exception to let Flask handle it with specific @errorhandler
             # Or potentially return the specific error handler's response directly
             if isinstance(e, werkzeug.exceptions.NotFound):
                 return page_not_found(e)
             if isinstance(e, werkzeug.exceptions.RequestEntityTooLarge):
                 return request_entity_too_large(e)
             return e # Default re-raise for other HTTP exceptions

        # Handle non-HTTP exceptions or those without specific handlers
        current_app.logger.error(f"Unhandled Exception: {request.path}", exc_info=e)
        return render_template('error.html', error_code=500, error_message="An unexpected error occurred."), 500