# app.py
import os
import sys # Needed for stderr output
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask
from config import config # Assuming config.py is in the same directory or install path
from flask_wtf.csrf import CSRFProtect # <-- Import CSRFProtect
from celery_app import celery # <--- IMPORTED Celery instance

# --- Optional: Add sys.path modification if blueprint_parser isn't installed as a package ---
# Ensure this runs only once if needed, e.g., by checking if path already exists
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = script_dir # Assuming app.py is in the root alongside blueprint_parser
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    print(f"INFO: Added {project_root} to sys.path for local imports.")
# -------------------------------------------------------------------------------------------

# --- Import chunked upload routes ---
try:
    from chunked_upload import add_chunked_upload_routes
    CHUNKED_UPLOAD_ENABLED = True
    # Optional: Add an initial log message here if desired, but logger might not be ready yet
    # print("INFO: Found chunked_upload module.")
except ImportError:
    add_chunked_upload_routes = None
    CHUNKED_UPLOAD_ENABLED = False
    # Use print for early warnings before logger might be configured
    print("WARNING: chunked_upload.py not found or cannot be imported. Chunked uploads will be disabled.")
# --- End Import ---


# --- Create a CSRF object that can be imported elsewhere ---
# Instantiate OUTSIDE the factory
csrf = CSRFProtect()
# ---------------------------------------------------------

def create_app(config_name=None): # Accept config_name, default handled below
    """Application Factory Function"""
    app = Flask(__name__)

    # --- Load Config FIRST ---
    # Determine config name based on FLASK_ENV, default to 'production' if not explicitly passed
    if config_name is None:
        config_name = os.environ.get('FLASK_ENV', 'production')

    # Validate config_name
    if config_name not in config:
        print(f"WARNING: Invalid FLASK_ENV or config name '{config_name}'. Defaulting to 'production'.", file=sys.stderr)
        config_name = 'production'

    try:
        app.config.from_object(config[config_name])
        print(f"INFO: Loading configuration '{config_name}' from config.py")
        # Ensure SECRET_KEY is set for CSRF
        if not app.config.get('SECRET_KEY'):
             print("CRITICAL ERROR: SECRET_KEY is not set in the configuration. CSRF protection requires it.", file=sys.stderr)
             sys.exit(1)
    except KeyError:
        print(f"CRITICAL ERROR: Configuration '{config_name}' not found in config.py!", file=sys.stderr)
        sys.exit(1) # Exit if config is fundamentally broken
    # --- Config loaded ---


    # --- Use app.debug (from config) as the SINGLE source of truth for debug status ---
    IS_DEBUG = app.debug # Get debug status directly from the loaded config
    # ---


    # --- Configure Logging ---
    log_level = logging.DEBUG if IS_DEBUG else logging.INFO # Use INFO for prod, DEBUG for dev
    log_format = '%(asctime)s %(levelname)s: %(message)s [%(pathname)s:%(lineno)d]'

    # Clear default handlers Flask might add
    # It's generally safe to keep these lines to ensure clean setup
    app.logger.handlers.clear()
    app.logger.propagate = False # Prevent root logger from handling Flask messages

    # Configure logging handlers based on environment

    # --- START MODIFICATION --- (This comment is kept for clarity, it was part of the provided block)
    # Always add a StreamHandler to stderr for visibility in PaaS logs (like Railway/Render)
    try:
        stream_handler = logging.StreamHandler(sys.stderr) # Log to stderr
        stream_handler.setFormatter(logging.Formatter(log_format))
        # Set level for this handler based on environment
        stream_handler.setLevel(log_level)
        app.logger.addHandler(stream_handler)
        # Use print here BEFORE logger might be fully ready, or log right after adding handler
        # print("Stderr logging configured.", file=sys.stderr) # Alternative initial confirmation
        app.logger.info("Stderr logging configured.") # Log confirmation using the configured logger
    except Exception as stream_log_e:
         # Use print as logger might not be fully working if this fails
         print(f"CRITICAL ERROR: Failed to configure stderr logging: {stream_log_e}", file=sys.stderr)
         # Depending on policy, you might exit here if basic logging fails
         # sys.exit(1)

    # Additionally, configure file logging for production if not debugging/testing
    if not IS_DEBUG and not app.testing: # Production logging to file
        try:
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, 'blueprint_parser.log')

            file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5) # 10MB * 5 files
            file_handler.setFormatter(logging.Formatter(log_format))
            # File handler usually logs INFO level even if stream handler logs DEBUG in dev
            file_handler.setLevel(logging.INFO) # Set file handler level (e.g., INFO)
            app.logger.addHandler(file_handler)
            app.logger.info("File logging configured for production.") # Log confirmation

        except Exception as log_e:
            # Log file setup failure TO STDERR via the already added stream_handler
            # Ensure the logger exists and has handlers before using it in except block
            if app.logger and app.logger.hasHandlers():
                 app.logger.error(f"Failed to configure file logging: {log_e}", exc_info=True)
            else:
                 # Fallback to print if logger failed critically before this point
                 print(f"ERROR: Failed to configure file logging: {log_e}. Logger unavailable.", file=sys.stderr)
            # No need for fallback stream handler here, as one was already added above

    # --- END MODIFICATION --- (This comment is kept for clarity, it was part of the provided block)

    app.logger.setLevel(log_level) # Set the overall minimum level for the logger instance
    # Make sure logger has handlers before logging the final init message
    if app.logger and app.logger.hasHandlers():
        app.logger.info(f'Flask app logging initialized. Config: {config_name}, Debug: {IS_DEBUG}, Level: {logging.getLevelName(log_level)}')
    else:
        print(f"WARNING: Logger initialization incomplete. Config: {config_name}, Debug: {IS_DEBUG}", file=sys.stderr)
    # --- End Logging Config ---


    # --- Initialize Celery ---  <--- ADDED THIS BLOCK ---
    try:
        # Update Celery config using the config loaded into the Flask app
        # This ensures Celery uses the correct broker/backend URLs defined for the env
        celery.conf.update(app.config)
        # Use .get with default for safer logging in case keys aren't in app.config
        app.logger.info(f"Celery broker: {celery.conf.get('CELERY_BROKER_URL', 'Not Set in app.config')}")
        app.logger.info(f"Celery backend: {celery.conf.get('CELERY_RESULT_BACKEND', 'Not Set in app.config')}")

        # Define Task subclass to ensure Flask app context is available
        class ContextTask(celery.Task):
            abstract = True # Ensure it's an abstract base class
            def __call__(self, *args, **kwargs):
                # The app context will always be available when the task is *called*
                # if it's set up within the factory like this.
                with app.app_context():
                    return self.run(*args, **kwargs)

        # Set the custom Task class as the default for this Celery instance
        celery.Task = ContextTask
        app.logger.info("Celery Task context configured.")

        # Optional: Store the celery instance in Flask extensions
        app.extensions["celery"] = celery

    except Exception as celery_e:
       app.logger.critical(f"Failed to initialize or configure Celery: {celery_e}", exc_info=True)
       # Depending on criticality, you might want to sys.exit(1) here too
       # If Celery is essential, uncomment the line below:
       # sys.exit(1)
    # --- End Celery Init ---


    # --- Import and Configure Parser Debug Flags INSIDE create_app ---
    # Define variables upfront to check existence after try block
    bp_parser_module = None
    bp_path_tracer_module = None
    bp_data_tracer_module = None
    bp_node_formatter_module = None
    try:
        # Import the specific modules needed to set flags
        from blueprint_parser import parser as bp_parser_module_imp
        bp_parser_module = bp_parser_module_imp
        from blueprint_parser.formatter import path_tracer as bp_path_tracer_module_imp
        bp_path_tracer_module = bp_path_tracer_module_imp
        from blueprint_parser.formatter import data_tracer as bp_data_tracer_module_imp
        bp_data_tracer_module = bp_data_tracer_module_imp
        from blueprint_parser.formatter import node_formatter as bp_node_formatter_module_imp
        bp_node_formatter_module = bp_node_formatter_module_imp

        # Check if imports succeeded before setting flags
        if all([bp_parser_module, bp_path_tracer_module, bp_data_tracer_module, bp_node_formatter_module]):
            # Set flags based *only* on IS_DEBUG (derived from the loaded config)
            bp_parser_module.ENABLE_PARSER_DEBUG = IS_DEBUG
            bp_path_tracer_module.ENABLE_PATH_TRACER_DEBUG = IS_DEBUG
            bp_data_tracer_module.ENABLE_TRACER_DEBUG = IS_DEBUG
            bp_node_formatter_module.ENABLE_NODE_FORMATTER_DEBUG = IS_DEBUG
            app.logger.info(f"Parser Debug Flags Set To: {IS_DEBUG}")
        else:
            app.logger.warning("One or more blueprint_parser modules failed to import. Cannot set debug flags.")

    except ImportError as e:
        app.logger.error(f"Failed to import blueprint_parser modules to set debug flags: {e}", exc_info=True)
    except Exception as e:
        app.logger.error(f"Failed to set blueprint_parser debug flags: {e}", exc_info=True)
    # --- End Parser Debug Flags ---


    # --- Initialize Extensions (like CSRF) ---
    try:
        # Use the global csrf object and initialize it with the app
        csrf.init_app(app) # <-- Use init_app here
        app.logger.info("CSRF protection initialized.")
    except ImportError:
        # This except block might not be strictly needed if you ensure Flask-WTF is installed,
        # but it's good practice for robustness if CSRFProtect was imported conditionally.
        # If CSRFProtect itself failed to import earlier, the app would likely fail before this.
        app.logger.warning("Flask-WTF not installed or CSRFProtect object unavailable. CSRF protection may be disabled.")
    except Exception as e:
        app.logger.critical(f"Failed to initialize CSRF protection: {e}", exc_info=True)
        sys.exit(1) # Exit if CSRF init fails, as it's security-critical
    # --- End Extensions ---


    # --- Register Routes ---
    try:
        # --- Register Main Routes ---
        from routes import register_routes
        register_routes(app) # Register main routes
        app.logger.info("Main routes registered successfully.")

        # --- Register Chunked Upload Routes --- # <--- NEW SECTION ADDED HERE ---
        if add_chunked_upload_routes and CHUNKED_UPLOAD_ENABLED:
            try: # Add inner try/except for the registration call itself
                 add_chunked_upload_routes(app) # Register chunked routes
                 app.logger.info("Chunked upload routes registered successfully.")
            except Exception as chunk_reg_e:
                 app.logger.error(f"Error registering chunked upload routes: {chunk_reg_e}", exc_info=True)
                 # Decide if this is critical. Probably not, so just log.
        elif not add_chunked_upload_routes:
             # This condition covers the case where the import failed earlier (at the top level)
             app.logger.warning("Chunked upload module not imported. Chunked upload routes *NOT* registered.")
        else:
             # This condition means import succeeded, but maybe CHUNKED_UPLOAD_ENABLED was manually set False
             # Or potentially add_chunked_upload_routes is None for some other reason.
             app.logger.warning("Chunked upload registration skipped (CHUNKED_UPLOAD_ENABLED is False or function unavailable).")
        # --- End Register Chunked Routes ---

    except ImportError as e:
        # This catches import errors for the *main* routes.py
        app.logger.critical(f"Failed to import or register main routes from routes.py: {e}", exc_info=True)
        raise RuntimeError("Could not register application routes.") from e # Re-raise critical error
    except Exception as route_reg_e: # Catch potential errors during main route registration too
        app.logger.critical(f"An error occurred during route registration: {route_reg_e}", exc_info=True)
        raise RuntimeError("Could not register application routes.") from route_reg_e
    # --- End Routes ---

    app.logger.info("Application setup complete.")
    return app

# --- Development Server Execution ---
# This block ONLY runs when executing `python app.py` directly
if __name__ == '__main__':
    print("INFO: Attempting to run development server...")

    # --- Always use 'development' config for direct run ---
    local_config_name_for_dev = 'development'
    print(f"INFO: Using config: '{local_config_name_for_dev}' for direct run")
    # ---

    # Create the app instance using the factory for local development
    # It will load DevelopmentConfig because we passed 'development'
    dev_app = create_app(local_config_name_for_dev)

    # The debug status for app.run comes DIRECTLY from the loaded DevelopmentConfig
    actual_debug_status = dev_app.debug # Should be True
    print(f"INFO: Running development server with actual debug={actual_debug_status}")

    try:
        # Run the development server
        # host='0.0.0.0' makes it accessible on your network
        # port=5001 is the port number
        # debug=actual_debug_status enables/disables the interactive debugger and reloader
        dev_app.run(host='0.0.0.0', port=5001, debug=actual_debug_status)
    except Exception as run_e:
        print(f"ERROR: Failed to run development server: {run_e}", file=sys.stderr)
        sys.exit(1)

# --- Production Entry Point ---
# No 'else' block needed. WSGI server (like Gunicorn via wsgi.py)
# will import this file and call create_app() itself via wsgi.py.