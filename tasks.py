# tasks.py
import time
import re
import logging
import traceback
from datetime import datetime

# --- Import Celery App ---
try:
    from celery_app import celery
    print("INFO (tasks.py): Successfully imported celery instance.")
except ImportError:
    logging.getLogger(__name__).critical("CRITICAL: Could not import 'celery' instance from celery_app.py!")
    print("ERROR (tasks.py): Could not import 'celery' instance from celery_app.py!")
    class DummyCelery:
        def task(self, *args, **kwargs):
            def decorator(func):
                return func
            return decorator
    celery = DummyCelery()

# --- Import Parser stuff ---
try:
    from blueprint_parser.parser import BlueprintParser
    from blueprint_parser.formatter.formatter import get_formatter
    from blueprint_parser.unsupported_nodes import get_unsupported_graph_type
    print("INFO (tasks.py): Successfully imported blueprint_parser components.")
except ImportError as e:
    logging.getLogger(__name__).critical(f"CRITICAL: Failed to import blueprint_parser in tasks.py: {e}", exc_info=True)
    print(f"ERROR (tasks.py): Failed to import blueprint_parser: {e}")
    # Define dummy classes/functions to prevent NameErrors if import fails
    class BlueprintParser: pass
    def get_formatter(f_type, p): return None
    def get_unsupported_graph_type(p): return None

# --- Import Rendering Utils ---
# ** Import blueprint_markdown again **
try:
    # Assuming rendering_utils.py is in the same directory or discoverable
    from rendering_utils import blueprint_markdown, html_escape # Import needed functions
    print("INFO (tasks.py): Successfully imported rendering utils (blueprint_markdown, html_escape).")
except ImportError as e_render:
    logging.getLogger(__name__).critical(f"CRITICAL: Failed to import rendering_utils: {e_render}", exc_info=True)
    print(f"ERROR (tasks.py): Failed to import rendering_utils: {e_render}")
    # Define dummy functions if import fails so the task can report error instead of crashing
    def blueprint_markdown(text, logger): return f"<p>Rendering Error (Import Failed): {html_escape(text)}</p>" # Dummy added back
    def html_escape(text): return text # Basic fallback

@celery.task(bind=True)
def parse_blueprint_task(self, blueprint_raw_text: str):
    """Celery task to parse, format, AND RENDER blueprint text.""" # Docstring updated
    task_id = self.request.id
    logger = logging.getLogger(__name__)
    logger.info(f"Task {task_id}: Starting parsing for input length {len(blueprint_raw_text)}")

    # Initialize results dictionary (must be JSON serializable)
    results = {
        "output": "",           # Will store RENDERED HTML
        "ai_output": "",        # Will store raw JSON string (or similar) for AI
        "stats_summary": "",    # Will store RENDERED HTML
        "error": "",            # Stores accumulated error messages
        "task_id": task_id,
        "status": "PROCESSING"  # Initial status
    }

    start_time = datetime.now()
    human_format_type = "enhanced_markdown" # Get raw markdown format
    ai_format_type = "ai_readable"          # Format for AI consumption

    try:
        # === START of Core Processing Logic (modified from original) ===

        # --- Unsupported type check ---
        detected_unsupported = None
        warning_message = ""
        is_unsupported = False
        try:
            logger.debug(f"Task {task_id}: Starting unsupported type pre-check...")
            preliminary_check_lines = blueprint_raw_text.splitlines()[:20]
            common_unsupported_hints = [
                "/Script/UnrealEd.MaterialGraphNode", "/Script/Engine.MaterialExpression",
                "/Script/AnimGraph.", "/Script/MetasoundEditor.", "/Script/NiagaraEditor.",
                "/Script/PCGEditor.", "/Script/AIGraph."
            ]
            for line in preliminary_check_lines:
                # More robust check covering different ways classes might be specified
                if 'Class=' in line or 'MaterialExpression' in line or 'GraphNode' in line or any(hint in line for hint in common_unsupported_hints):
                    class_path = None
                    # Try extracting from Class=...
                    class_match = re.search(r'Class=(?:ObjectProperty|SoftObjectProperty)?\'?\"?(/[^\"\']+)', line)
                    if class_match:
                        class_path = class_match.group(1).strip("'\"")
                    else:
                        # Fallback: check for known hints directly if Class= not found or doesn't match pattern
                        for hint in common_unsupported_hints:
                            if hint in line:
                                class_path = hint
                                break # Found a hint

                    if class_path:
                        unsupported_type = get_unsupported_graph_type(class_path) # Needs function import
                        if unsupported_type:
                            detected_unsupported = unsupported_type
                            is_unsupported = True
                            logger.debug(f"Task {task_id}: Detected unsupported type hint: {unsupported_type} from path/hint: {class_path}")
                            break # Stop checking lines once an unsupported type is confirmed

            if detected_unsupported:
                warning_message = f"Warning: Input appears to be an unsupported graph type ({detected_unsupported}). Results may be incomplete or inaccurate."
                logger.info(f"Task {task_id}: {warning_message}")
        except ImportError:
            logger.warning(f"Task {task_id}: Could not import 'unsupported_nodes' module for pre-check.", exc_info=True)
        except Exception as pre_check_err:
            logger.warning(f"Task {task_id}: Error during unsupported node pre-check: {pre_check_err}", exc_info=True)
        # --- End unsupported check ---

        logger.info(f"Task {task_id}: Instantiating BlueprintParser...")
        parser = BlueprintParser() # Ensure class is imported

        logger.info(f"Task {task_id}: Starting parser.parse()...")
        nodes = parser.parse(blueprint_raw_text) # Use the task argument
        node_count = len(nodes) if nodes else 0
        comment_count = len(parser.comments) if parser.comments else 0
        logger.info(f"Task {task_id}: Parsing finished. Nodes: {node_count}, Comments: {comment_count}")

        raw_human_output = "" # Store raw markdown here
        raw_stats_summary = "" # Store raw stats markdown here

        if not nodes and not parser.comments and not detected_unsupported:
            # Update results dict instead of local variable
            results['error'] = "No valid Blueprint nodes or comments found in the input."
            logger.warning(f"Task {task_id}: Parsing resulted in no nodes or comments.")
            # No further processing needed if nothing was parsed and it's not an unsupported type warning case

        elif nodes or parser.comments:
            # Proceed with formatting even if nodes/comments are found alongside an unsupported warning
            logger.info(f"Task {task_id}: Getting formatters...")
            human_formatter = get_formatter(human_format_type, parser) # Ensure func imported
            if human_formatter:
                 # Store RAW markdown output temporarily
                 raw_human_output = human_formatter.format_graph(input_filename="Pasted Blueprint")
                 raw_stats_summary = human_formatter.format_statistics()
                 logger.info(f"Task {task_id}: Raw Human formatting finished.")
            else:
                 error_msg = "Failed to get human formatter."
                 results['error'] = f"{results['error']}\n{error_msg}".strip()
                 logger.error(f"Task {task_id}: {error_msg}")

            ai_formatter = get_formatter(ai_format_type, parser)
            if ai_formatter:
                 # Update results dict directly with the AI output (usually JSON string)
                 results['ai_output'] = ai_formatter.format_graph(input_filename="Pasted Blueprint")
                 logger.info(f"Task {task_id}: AI formatting finished.")
            else:
                 error_msg = "Failed to get AI formatter."
                 results['error'] = f"{results['error']}\n{error_msg}".strip()
                 logger.error(f"Task {task_id}: {error_msg}")

            # --- *** RENDER MARKDOWN TO HTML HERE (Restored) *** ---
            logger.info(f"Task {task_id}: Rendering Markdown to HTML...")
            try:
                 if raw_human_output:
                     rendered_output_markup = blueprint_markdown(raw_human_output, logger) # CALL RENDERER
                     results['output'] = str(rendered_output_markup) # Store rendered HTML
                 if raw_stats_summary:
                     rendered_stats_markup = blueprint_markdown(raw_stats_summary, logger) # CALL RENDERER
                     results['stats_summary'] = str(rendered_stats_markup) # Store rendered HTML
                 logger.info(f"Task {task_id}: Markdown rendering finished.")
            except Exception as render_err:
                 logger.error(f"Task {task_id}: Failed Markdown rendering: {render_err}", exc_info=True)
                 render_error_msg = f"Error rendering output: {html_escape(str(render_err))}"
                 results['error'] = f"{results['error']}\n{render_error_msg}".strip()
                 # Fallback output includes error message and raw markdown
                 results['output'] = f"<p><strong>{render_error_msg}. Raw markdown below:</strong></p><pre><code>{html_escape(raw_human_output)}</code></pre>"
                 results['stats_summary'] = f"<p><strong>Error rendering stats. Raw markdown below:</strong></p><pre><code>{html_escape(raw_stats_summary)}</code></pre>"
            # --- *** END MARKDOWN RENDERING *** ---

            # Prepend warning (to RENDERED HTML output) if applicable
            # This modifies results['output'] which now contains HTML (or fallback HTML)
            if is_unsupported and warning_message:
                 logger.info(f"Task {task_id}: Prepending unsupported type warning to rendered output.")
                 escaped_warning = html_escape(warning_message) # Use helper for safety
                 # Prepend HTML snippet to the RENDERED HTML string
                 results['output'] = f"<div class='alert alert-warning'>{escaped_warning}</div>\n\n" + str(results['output'])
                 # Also add the warning to the error field for clarity in status
                 results['error'] = f"{results['error']}\n{warning_message}".strip()

        elif detected_unsupported and warning_message:
              # Case: No nodes/comments found, BUT an unsupported type was detected.
              # The main error is the warning itself.
              results['error'] = warning_message
              # Provide basic warning output as HTML
              results['output'] = f"<div class='alert alert-warning'>{html_escape(warning_message)}</div>"
              logger.warning(f"Task {task_id}: Parsing found no nodes/comments, but an unsupported type was detected: {detected_unsupported}")


    except ImportError as e_imp:
        # Catch potential import errors during the main processing block if dummies failed
        logger.critical(f"Task {task_id}: Runtime Import Error during processing: {e_imp}", exc_info=True)
        error_msg = f"Server Error: A required component could not be loaded ({e_imp})."
        results['error'] = f"{results['error']}\n{error_msg}".strip()
        results['status'] = "FAILURE" # Critical failure
    except Exception as e_proc:
        # Catch any other unexpected error during parsing/formatting/rendering
        logger.error(f"Task {task_id}: EXCEPTION during core processing: {e_proc}", exc_info=True)
        error_msg = f"An unexpected error occurred during processing: {html_escape(str(e_proc))}. Check server logs."
        results['error'] = f"{results['error']}\n{error_msg}".strip()
        results['status'] = "FAILURE" # Mark as failure
        # Add traceback to error in debug/staging? Avoid in production unless needed.
        # results['error'] += f"\n<pre><code>{html_escape(traceback.format_exc())}</code></pre>"

    # === END of Core Processing Logic ===

    end_time = datetime.now()
    duration = end_time - start_time

    # Final status update based on accumulated errors
    if results['status'] != "FAILURE": # If not already marked as a critical failure
        if results['error']:
            # If there were errors (like formatting failed, rendering failed, or unsupported warning)
            # but some output might still exist.
            results['status'] = "PARTIAL_FAILURE"
        else:
            # No errors accumulated, processing was successful.
            results['status'] = "SUCCESS"

    logger.info(f"Task {task_id}: Processing complete. Duration: {duration}. Status: {results['status']}. Error: '{results['error'][:150]}...'")

    # The return value (the results dictionary) will be stored in the Celery result backend
    return results # Return dict with RENDERED HTML in 'output'/'stats_summary'