# tasks.py
# --- Phase 1 Refactor: Downloads input from R2/S3, cleans up S3 object ---

import time
import re
import logging
import traceback
import os # Added for env var fallback
import json # Added for parts parsing if needed
from datetime import datetime

import boto3 # Added
from botocore.exceptions import ClientError # Added for S3 error handling
from flask import current_app # Added to access config

# --- Import Celery App ---
try:
    from celery_app import celery
    print("INFO (tasks.py): Successfully imported celery instance.")
except ImportError:
    # Basic logging if Flask logger isn't available yet
    logging.getLogger(__name__).critical("CRITICAL: Could not import 'celery' instance from celery_app.py!")
    print("ERROR (tasks.py): Could not import 'celery' instance from celery_app.py!")
    # Define a dummy decorator if Celery is unavailable
    class DummyCeleryTask:
        def __init__(self, *args, **kwargs): pass
        def __call__(self, f): return f
    class DummyCelery:
        def task(self, *args, **kwargs): return DummyCeleryTask()
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
try:
    from rendering_utils import blueprint_markdown, html_escape
    print("INFO (tasks.py): Successfully imported rendering utils.")
except ImportError as e_render:
    logging.getLogger(__name__).critical(f"CRITICAL: Failed to import rendering_utils: {e_render}", exc_info=True)
    print(f"ERROR (tasks.py): Failed to import rendering_utils: {e_render}")
    # Define dummy functions
    def blueprint_markdown(text, logger): return f"<p>Rendering Error (Import Failed): {html_escape(text)}</p>"
    def html_escape(text): return str(text).replace('&', '&').replace('<', '<').replace('>', '>')

# --- S3 Client Helper for Task Context ---
# tasks.py

def get_s3_client_for_task():
    """Gets a boto3 S3 client instance using Flask app config within task context."""
    logger = logging.getLogger(__name__)
    endpoint_url = None
    access_key = None
    secret_key = None
    # --- CORRECTED LINE ---
    region_name = 'auto' # Use 'auto' region for R2
    # --- END CORRECTION ---

    try:
        if current_app:
            endpoint_url = current_app.config.get('R2_ENDPOINT_URL')
            access_key = current_app.config.get('R2_ACCESS_KEY_ID')
            secret_key = current_app.config.get('R2_SECRET_ACCESS_KEY')
            # Region is now fixed to 'auto', no need to derive
            logger.debug("S3 config loaded from Flask app context.")
        else:
            logger.warning("No Flask app context in task. Attempting to load S3 config from environment.")
            endpoint_url = os.environ.get('R2_ENDPOINT_URL')
            access_key = os.environ.get('R2_ACCESS_KEY_ID')
            secret_key = os.environ.get('R2_SECRET_ACCESS_KEY')
            # Region is fixed to 'auto'
    except Exception as config_e:
         logger.error(f"Error accessing config for S3 client: {config_e}", exc_info=True)
         raise ValueError("Could not load S3 configuration.")


    if not all([endpoint_url, access_key, secret_key]):
         logger.error("Missing R2/S3 configuration for task S3 client (Endpoint, Key ID, Secret Key).")
         raise ValueError("Missing R2/S3 configuration for task S3 client.")

    try:
        client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region_name # Use 'auto'
        )
        logger.debug(f"Task S3 client created for endpoint {endpoint_url} with region '{region_name}'.")
        return client
    except Exception as e:
        logger.error(f"Failed to create S3 client in task for {endpoint_url}: {e}")
        raise

    
# --- Celery Task ---
@celery.task(bind=True)
def parse_blueprint_task(self, s3_bucket: str, s3_key: str): # Modified signature
    """Celery task to download from R2, parse, format, and optionally render blueprint text."""
    task_id = self.request.id
    # Use standard logging; Flask app logger might not be directly available easily
    # but Celery logging should be configured.
    logger = logging.getLogger(__name__)
    logger.info(f"Task {task_id}: Starting processing for S3 object s3://{s3_bucket}/{s3_key}")

    # Initialize results dictionary (must be JSON serializable)
    results = {
        "output_markdown": "",    # Store RAW markdown
        "ai_output": "",        # Store raw JSON string for AI
        "stats_markdown": "",     # Store RAW stats markdown
        "error": "",            # Stores accumulated error messages
        "task_id": task_id,
        "status": "PROCESSING"  # Initial status
        # Phase 2: Add 'user_id' field here if needed for history view
    }

    s3_client = None # Initialize S3 client variable
    blueprint_raw_text = None

    try:
        # --- Download from R2/S3 ---
        s3_client = get_s3_client_for_task() # Get S3 client
        logger.info(f"Task {task_id}: Downloading from R2/S3...")
        start_download = time.time()
        s3_response = s3_client.get_object(Bucket=s3_bucket, Key=s3_key)
        blueprint_raw_text = s3_response['Body'].read().decode('utf-8')
        download_time = time.time() - start_download
        logger.info(f"Task {task_id}: Downloaded {len(blueprint_raw_text)} chars from R2/S3 in {download_time:.2f}s.")
        # --- End Download ---

        # === START of Core Processing Logic (using blueprint_raw_text) ===
        start_time = datetime.now()
        human_format_type = "enhanced_markdown" # Get raw markdown format
        ai_format_type = "ai_readable"          # Format for AI consumption

        # --- Unsupported type check (Keep this logic) ---
        detected_unsupported = None
        warning_message = ""
        is_unsupported = False
        try:
            # ... (existing unsupported check logic using blueprint_raw_text) ...
             preliminary_check_lines = blueprint_raw_text.splitlines()[:20]
             # ... rest of the check ...
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
        nodes = parser.parse(blueprint_raw_text) # Use the downloaded text
        node_count = len(nodes) if nodes else 0
        comment_count = len(parser.comments) if parser.comments else 0
        logger.info(f"Task {task_id}: Parsing finished. Nodes: {node_count}, Comments: {comment_count}")

        raw_human_output = "" # Store raw markdown here
        raw_stats_summary = "" # Store raw stats markdown here

        if not nodes and not parser.comments and not detected_unsupported:
            results['error'] = "No valid Blueprint nodes or comments found in the input."
            logger.warning(f"Task {task_id}: Parsing resulted in no nodes or comments.")
        elif nodes or parser.comments or detected_unsupported: # Process even if only unsupported detected
            # Formatting logic (produces raw Markdown)
            logger.info(f"Task {task_id}: Getting formatters...")
            human_formatter = get_formatter(human_format_type, parser)
            if human_formatter:
                 results['output_markdown'] = human_formatter.format_graph(input_filename="Pasted Blueprint") # Store RAW markdown
                 results['stats_markdown'] = human_formatter.format_statistics() # Store RAW stats markdown
                 logger.info(f"Task {task_id}: Raw Human formatting finished.")
            else:
                 error_msg = "Failed to get human formatter."
                 results['error'] = f"{results['error']}\n{error_msg}".strip()
                 logger.error(f"Task {task_id}: {error_msg}")

            ai_formatter = get_formatter(ai_format_type, parser)
            if ai_formatter:
                 results['ai_output'] = ai_formatter.format_graph(input_filename="Pasted Blueprint") # Store AI output (JSON string)
                 logger.info(f"Task {task_id}: AI formatting finished.")
            else:
                 error_msg = "Failed to get AI formatter."
                 results['error'] = f"{results['error']}\n{error_msg}".strip()
                 logger.error(f"Task {task_id}: {error_msg}")

            # --- Rendering is now done in the Flask route ---

            # Prepend warning (to raw markdown output) if applicable
            if is_unsupported and warning_message:
                 logger.info(f"Task {task_id}: Prepending unsupported type warning to raw markdown output.")
                 # Add warning prominently in the markdown
                 warning_md = f"> **Warning:** {warning_message}\n\n---\n\n"
                 results['output_markdown'] = warning_md + results['output_markdown']
                 results['error'] = f"{results['error']}\n{warning_message}".strip() # Also add to error field

        # Handle case where only unsupported type was found
        elif detected_unsupported and warning_message and not results['output_markdown']:
              results['error'] = warning_message
              results['output_markdown'] = f"> **Warning:** {warning_message}" # Basic warning as output
              logger.warning(f"Task {task_id}: Parsing found no nodes/comments, but an unsupported type was detected: {detected_unsupported}")

        # === END of Core Processing Logic ===

    except ClientError as s3_e:
        logger.error(f"Task {task_id}: R2/S3 Error during processing: {s3_e}", exc_info=True)
        results['error'] = f"Server Error: Could not retrieve input file from storage. Code: {s3_e.response.get('Error', {}).get('Code', 'Unknown')}"
        results['status'] = "FAILURE"
    except ImportError as e_imp:
        logger.critical(f"Task {task_id}: Runtime Import Error during processing: {e_imp}", exc_info=True)
        error_msg = f"Server Error: A required component could not be loaded ({e_imp})."
        results['error'] = f"{results['error']}\n{error_msg}".strip()
        results['status'] = "FAILURE" # Critical failure
    except Exception as e_proc:
        logger.error(f"Task {task_id}: EXCEPTION during core processing: {e_proc}", exc_info=True)
        error_msg = f"An unexpected error occurred during processing: {str(e_proc)}. Check server logs."
        # Use html_escape defensively here in case error message contains HTML-like chars
        safe_error_msg = f"An unexpected error occurred during processing: {html_escape(str(e_proc))}. Check server logs."
        results['error'] = f"{results['error']}\n{safe_error_msg}".strip()
        results['status'] = "FAILURE" # Mark as failure
        # Optional: Add traceback for debugging
        # results['error'] += f"\n\nTraceback:\n{html_escape(traceback.format_exc())}"
    finally:
        # --- R2/S3 Cleanup ---
        if s3_client and s3_bucket and s3_key:
            try:
                logger.warning(f"Task {task_id}: Attempting to delete R2/S3 object: s3://{s3_bucket}/{s3_key}")
                s3_client.delete_object(Bucket=s3_bucket, Key=s3_key)
                logger.info(f"Task {task_id}: Successfully deleted R2/S3 object: {s3_key}")
            except ClientError as s3_del_e:
                # Log error but don't fail the task result just because cleanup failed
                logger.error(f"Task {task_id}: Failed to delete R2/S3 object s3://{s3_bucket}/{s3_key}: {s3_del_e}", exc_info=True)
        # --- End R2/S3 Cleanup ---

    # Final status update based on accumulated errors
    if results['status'] != "FAILURE": # If not already marked as a critical failure
        if results['error']:
            results['status'] = "PARTIAL_FAILURE" # Had warnings or non-critical errors
        else:
            results['status'] = "SUCCESS"

    # Calculate duration if start_time was set
    duration_str = "N/A"
    if 'start_time' in locals():
        end_time = datetime.now()
        duration = end_time - start_time
        duration_str = str(duration)

    logger.info(f"Task {task_id}: Processing complete. Duration: {duration_str}. Status: {results['status']}. Error: '{results['error'][:150]}...'")

    # Return dict with RAW markdown in 'output_markdown'/'stats_markdown'
    # Rendering will happen in the Flask route handler
    return results