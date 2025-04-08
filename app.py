# --- START OF FILE app.py ---

# ... (imports remain the same) ...
import os
import sys
import json
import markdown
import bleach
import re # Added import
import uuid # <--- ADD THIS LINE
from datetime import datetime # Correctly imported
from flask import Flask, render_template, request, jsonify
from markupsafe import Markup

# Dynamically add the blueprint_parser directory to sys.path
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)
parser_package_dir = os.path.join(project_root, 'blueprint_parser')

if project_root not in sys.path:
    sys.path.insert(0, project_root)
    print(f"Added project root {project_root} to sys.path for package import")

try:
    import blueprint_parser
    from blueprint_parser.parser import BlueprintParser
    from blueprint_parser.formatter.formatter import get_formatter # Corrected import path
    # Import debug flags if needed
    from blueprint_parser import parser as bp_parser_module
    from blueprint_parser.formatter import path_tracer as bp_path_tracer_module
    from blueprint_parser.formatter import data_tracer as bp_data_tracer_module
    from blueprint_parser.formatter import node_formatter as bp_node_formatter_module

    # --- Enable Debug Flags ---
    bp_parser_module.ENABLE_PARSER_DEBUG = True
    bp_path_tracer_module.ENABLE_PATH_TRACER_DEBUG = True
    bp_data_tracer_module.ENABLE_TRACER_DEBUG = True
    bp_node_formatter_module.ENABLE_NODE_FORMATTER_DEBUG = True
    # --------------------------

    print("Successfully imported blueprint_parser modules.")
except ImportError as e:
    print(f"Error importing blueprint_parser: {e}", file=sys.stderr)
    print("Current sys.path:", sys.path, file=sys.stderr)
    print("Ensure the 'blueprint_parser' directory exists in the project root folder.", file=sys.stderr)
    sys.exit(1)
# ... (rest of imports and setup) ...

app = Flask(__name__)

# --- Add Blueprint Markdown Filter ---

# Create a markdown filter for Jinja2 templates
# Create a markdown filter for Jinja2 templates
def blueprint_markdown(text):
    """Convert markdown to HTML with special handling for blueprint code blocks."""
    if not text:
        return Markup("")

    local_placeholder_storage = {}

    # Step 1: Replace blueprint blocks with unique HTML comment placeholders
    def replace_blueprint_block(match):
        # Generate a unique ID for the placeholder
        placeholder_uuid = str(uuid.uuid4())
        placeholder_comment = f"<!-- BP_PLACEHOLDER_{placeholder_uuid} -->"
        local_placeholder_storage[placeholder_comment] = match.group(1)
        # print(f"  Placeholder created: {placeholder_comment} for content length {len(match.group(1))}") # DEBUG
        return placeholder_comment

    text_with_placeholders = re.sub(
        r'```blueprint\r?\n(.*?)\r?\n```',
        replace_blueprint_block,
        text,
        flags=re.DOTALL | re.IGNORECASE
    )
    # print(f"Placeholders generated: {list(local_placeholder_storage.keys())}") # DEBUG

    # Step 2: Convert the modified Markdown (with placeholders) to HTML
    try:
        html = markdown.markdown(
            text_with_placeholders,
            extensions=['markdown.extensions.tables', 'markdown.extensions.fenced_code', 'markdown.extensions.nl2br']
        )
        # print("Markdown conversion successful.") # DEBUG
    except Exception as e:
        print(f"ERROR during markdown conversion: {e}") # DEBUG
        return Markup(f"<p>Error during Markdown processing: {e}</p>")

    # Step 3: Replace placeholders with formatted <pre><code> blocks AFTER markdown
    if local_placeholder_storage:
        # print("Starting placeholder replacement...") # DEBUG
        for placeholder_comment, raw_blueprint_code in local_placeholder_storage.items():
            # Only escape essential HTML characters to preserve code formatting chars
            escaped_content = raw_blueprint_code.replace('&', '&').replace('<', '<').replace('>', '>')

            # Construct the final HTML for the blueprint block
            blueprint_html = f'<pre class="blueprint"><code>{escaped_content}</code></pre>'

            # Replace the placeholder comment in the main HTML
            if placeholder_comment in html:
                html = html.replace(placeholder_comment, blueprint_html)
                # print(f"    Replaced '{placeholder_comment}'.") # DEBUG
            # else:
                # print(f"    WARNING: Placeholder '{placeholder_comment}' not found in generated HTML.") # DEBUG

    local_placeholder_storage.clear()
    # print("Placeholder replacement finished.") # DEBUG

    # Step 4: Sanitize the *entire* final HTML
    # print("Starting HTML sanitization...") # DEBUG
    allowed_tags = bleach.sanitizer.ALLOWED_TAGS | {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'hr',
                   'strong', 'em', 'ul', 'ol', 'li', 'pre', 'code', # Ensure pre/code are allowed
                   'a', 'span', 'div', 'img', 'table', 'thead', 'tbody',
                   'tr', 'th', 'td', 'blockquote'}

    allowed_attrs = {
        '*': ['class', 'id', 'style', 'title'],
        'a': ['href', 'title', 'id', 'class', 'target'],
        'img': ['src', 'alt', 'title', 'width', 'height', 'style'],
        'code': ['class'], # Allow class on code (e.g., language-blueprint if added by fenced_code)
        'pre': ['class'], # Allow class on pre (e.g., blueprint)
        'blockquote': ['class'],
        'span': ['class', 'style']
    }

    try:
        clean_html = bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs, strip=True)
        # print("HTML sanitization successful.") # DEBUG
    except Exception as e:
        print(f"ERROR during HTML sanitization: {e}") # DEBUG
        clean_html = f"<p>Error during HTML sanitization: {e}</p>" + html # Show error and original HTML

    # Step 5: Add specific formatting AFTER sanitization
    clean_html = clean_html.replace('→', '<span class="bp-arrow">→</span>')

    return Markup(clean_html)

# Register the filter with Flask
app.jinja_env.filters['markdown'] = blueprint_markdown

# --- End Blueprint Markdown Filter ---

@app.route('/', methods=['GET', 'POST'])
def index():
    output = ""
    ai_output = ""
    error = ""
    stats_summary = ""
    raw_text = request.form.get('blueprint_text', '')

    # Default formats (ensure these match the class names/keys in get_formatter)
    human_format_type = "enhanced_markdown"
    ai_format_type = "ai_readable"

    if request.method == 'POST':
        if not raw_text:
            error = "Please paste some Blueprint text."
        else:
            start_time = datetime.now()
            print(f"Processing request at {start_time}...")
            try:
                parser = BlueprintParser()
                nodes = parser.parse(raw_text)

                if not nodes and not parser.comments:
                     error = "No valid Blueprint nodes or comments found in the input."
                else:
                    # Get Human readable output
                    human_formatter = get_formatter(human_format_type, parser)
                    output = human_formatter.format_graph(input_filename="Pasted Blueprint")
                    stats_summary = human_formatter.format_statistics() # Get stats from the formatter

                    # Get AI-readable output
                    ai_formatter = get_formatter(ai_format_type, parser)
                    ai_output = ai_formatter.format_graph(input_filename="Pasted Blueprint")

                    # Debug prints
                    # print(f"Output type: {type(output)}")
                    # print(f"Output first 100 chars: {output[:100] if output else 'None'}")
                    # print(f"AI output first 100 chars: {ai_output[:100] if ai_output else 'None'}")
                    print(f"Output size: {len(output)}, AI output size: {len(ai_output)}")

            except ImportError as e:
                 print(f"Runtime Import Error: {e}", file=sys.stderr)
                 error = f"A required module could not be imported: {e}. Please check server logs."
            except Exception as e:
                 print(f"An error occurred during processing: {e}", file=sys.stderr)
                 import traceback
                 traceback.print_exc()
                 error = f"An unexpected error occurred: {e}. Check input or server logs for details."

            end_time = datetime.now()
            print(f"Processing finished at {end_time}. Duration: {end_time - start_time}")

    return render_template('index.html',
                          blueprint_output=output,
                          ai_output=ai_output,
                          error_message=error,
                          raw_blueprint_text=raw_text,
                          stats_summary=stats_summary) # Pass stats to template


if __name__ == '__main__':
    # Use a secret key for session management if needed, especially if storing placeholders
    app.config['SECRET_KEY'] = os.urandom(24)
    app.run(debug=True, host='0.0.0.0', port=5001)


# --- END OF FILE app.py ---