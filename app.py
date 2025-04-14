# app.py
import os
import sys # Needed for stderr output
import logging
from logging.handlers import RotatingFileHandler
from flask import Flask
from config import config # Assuming config.py is in the same directory or install path

# --- Optional: Add sys.path modification if blueprint_parser isn't installed as a package ---
# Ensure this runs only once if needed, e.g., by checking if path already exists
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = script_dir # Assuming app.py is in the root alongside blueprint_parser
if project_root not in sys.path:
    sys.path.insert(0, project_root)
    print(f"INFO: Added {project_root} to sys.path for local imports.")
# -------------------------------------------------------------------------------------------

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
    app.logger.handlers.clear()
    app.logger.propagate = False

    # Configure logging handlers based on environment
    if not IS_DEBUG and not app.testing: # Production logging to file
        try:
            log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logs')
            os.makedirs(log_dir, exist_ok=True)
            log_file = os.path.join(log_dir, 'blueprint_parser.log')

            file_handler = RotatingFileHandler(log_file, maxBytes=10*1024*1024, backupCount=5) # 10MB * 5 files
            file_handler.setFormatter(logging.Formatter(log_format))
            file_handler.setLevel(log_level)
            app.logger.addHandler(file_handler)
        except Exception as log_e:
            print(f"ERROR: Failed to configure file logging: {log_e}", file=sys.stderr)
            # Fallback to console logging even in production if file logging fails
            stream_handler = logging.StreamHandler(sys.stderr)
            stream_handler.setFormatter(logging.Formatter(log_format))
            stream_handler.setLevel(log_level)
            app.logger.addHandler(stream_handler)
            app.logger.error("File logging setup failed, falling back to stream handler.")

    else: # Development or testing logging (to console)
        stream_handler = logging.StreamHandler(sys.stderr) # Log to stderr for dev
        stream_handler.setFormatter(logging.Formatter(log_format))
        stream_handler.setLevel(log_level)
        app.logger.addHandler(stream_handler)

    app.logger.setLevel(log_level) # Set the overall logger level
    app.logger.info(f'Flask app created with config: {config_name}, Debug: {IS_DEBUG}')
    # --- End Logging Config ---


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
        from flask_wtf.csrf import CSRFProtect
        csrf = CSRFProtect(app)
        app.logger.info("CSRF protection initialized.")
    except ImportError:
        app.logger.warning("Flask-WTF not installed. CSRF protection disabled.")
    # --- End Extensions ---


    # --- Register Routes ---
    try:
        from routes import register_routes
        register_routes(app)
        app.logger.info("Routes registered successfully.")
    except ImportError as e:
         app.logger.critical(f"Failed to import or register routes from routes.py: {e}", exc_info=True)
         raise RuntimeError("Could not register application routes.") from e # Re-raise critical error
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