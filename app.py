# app.py
import os
import sys
import json
import markdown
import bleach
import re
import uuid
from datetime import datetime
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
    from blueprint_parser.formatter.formatter import get_formatter
    # Import debug flags if needed
    from blueprint_parser import parser as bp_parser_module
    from blueprint_parser.formatter import path_tracer as bp_path_tracer_module
    from blueprint_parser.formatter import data_tracer as bp_data_tracer_module
    from blueprint_parser.formatter import node_formatter as bp_node_formatter_module

    # --- Enable Debug Flags ---
    # Set these to False in production for better performance
    bp_parser_module.ENABLE_PARSER_DEBUG = False
    bp_path_tracer_module.ENABLE_PATH_TRACER_DEBUG = False
    bp_data_tracer_module.ENABLE_TRACER_DEBUG = False
    bp_node_formatter_module.ENABLE_NODE_FORMATTER_DEBUG = False
    # --------------------------

    print("Successfully imported blueprint_parser modules.")
except ImportError as e:
    print(f"Error importing blueprint_parser: {e}", file=sys.stderr)
    print("Current sys.path:", sys.path, file=sys.stderr)
    print("Ensure the 'blueprint_parser' directory exists in the project root folder.", file=sys.stderr)
    sys.exit(1)

app = Flask(__name__)

# --- ADD THIS LINE ---
# Increase the maximum request size (e.g., to 100MB)
# Adjust the size as needed (value is in bytes)
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024 # 100 MB limit
# --------------------

# --- ADD DEBUG PRINT 1 ---
print(f"DEBUG: MAX_CONTENT_LENGTH set to: {app.config.get('MAX_CONTENT_LENGTH')}")
# -------------------------

def html_escape(text):
    """Escapes text for use in HTML attribute values."""
    if not text:
        return ""
    return text.replace('&', '&amp;').replace('"', '&quot;').replace("'", "&#39;")

def clean_html_entities(html_content):
    """Normalize HTML entities to prevent double escaping."""
    # Fix double-escaped entities
    replacements = [
        ('&amp;lt;', '&lt;'),
        ('&amp;gt;', '&gt;'),
        ('&amp;amp;', '&amp;'),
        ('&amp;quot;', '&quot;'),
        ('&amp;#39;', '&#39;')
    ]
    for old, new in replacements:
        html_content = html_content.replace(old, new)
    return html_content

# Create a markdown filter for Jinja2 templates
def blueprint_markdown(text):
    """Convert markdown to HTML, preserving blueprint code blocks with spans intact."""
    if not text:
        return Markup("")

    # Important: Store spans in preprocessed blocks
    local_placeholder_storage = {}

    # Replace blueprint code blocks with placeholders before markdown processing
    def replace_blueprint_block(match):
        block_content = match.group(1)
        placeholder_uuid = str(uuid.uuid4())
        placeholder_comment = f"<!-- BP_PLACEHOLDER_{placeholder_uuid} -->"
        local_placeholder_storage[placeholder_comment] = block_content
        return placeholder_comment

    # Replace ```blueprint blocks with placeholders
    text_with_placeholders = re.sub(
        r'```blueprint\r?\n(.*?)\r?\n```',
        replace_blueprint_block,
        text,
        flags=re.DOTALL | re.IGNORECASE
    )

    # Parse markdown, avoiding blueprint blocks
    try:
        html = markdown.markdown(
            text_with_placeholders,
            extensions=['markdown.extensions.tables', 'markdown.extensions.fenced_code', 'markdown.extensions.nl2br']
        )
    except Exception as e:
        print(f"ERROR during markdown conversion: {e}")
        return Markup(f"<p>Error during Markdown processing: {e}</p>")

    # Now restore the blueprint blocks, making sure to NOT encode any HTML
    for placeholder, content in local_placeholder_storage.items():
        # Store the raw span content with explicit encoding prevention
        # We add both nohighlight attribute and explicit blueprint class
        blueprint_html = f'<pre class="blueprint"><code class="nohighlight blueprint-code" data-nohighlight="true">{content}</code></pre>'
        html = html.replace(placeholder, blueprint_html)

    # Process tables to ensure proper styling
    html = process_blueprint_tables(html, preserve_params=True)

    # Use a relaxed HTML sanitizer that allows our spans and classes
    allowed_tags = bleach.sanitizer.ALLOWED_TAGS | {'p', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'hr',
               'strong', 'em', 'ul', 'ol', 'li', 'pre', 'code', 'span', 'div',
               'a', 'img', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'blockquote'}

    allowed_attrs = {
        '*': ['class', 'id', 'style', 'data-nohighlight'],
        'a': ['href', 'title', 'id', 'class', 'target'],
        'img': ['src', 'alt', 'title', 'width', 'height'],
        'code': ['class', 'data-nohighlight'],
        'pre': ['class'],
        'span': ['class', 'style'],  # Allow span to have class and style
        'td': ['colspan', 'rowspan', 'style', 'class'],
        'th': ['colspan', 'rowspan', 'style', 'class'],
        'div': ['class', 'style', 'id']
    }

    try:
        clean_html = bleach.clean(html, tags=allowed_tags, attributes=allowed_attrs, strip=True)
        # Additional cleaning to fix any double-escaped spans
        clean_html = clean_html_entities(clean_html)
    except Exception as e:
        print(f"ERROR during HTML sanitization: {e}")
        clean_html = f"<p>Error during HTML sanitization: {e}</p>"
    
    return Markup(clean_html)

# --- Keep process_blueprint_tables function ---
def process_blueprint_tables(html, preserve_params=True):
    """Process and enhance tables in Blueprint output."""
    # Find tables using regex (basic approach)
    table_pattern = r'<table(.*?)>(.*?)</table>'

    def process_table_match(match):
        table_attrs = match.group(1)
        table_content = match.group(2)

        # Add a general class for styling
        if 'class=' not in table_attrs:
            table_attrs += ' class="blueprint-table"'
        elif 'blueprint-table' not in re.search(r'class=["\'](.*?)["\']', table_attrs).group(1):
             table_attrs = re.sub(r'class=(["\'])', r'class=\1blueprint-table ', table_attrs, 1)

        # Rebuild the table tag
        processed_table = f'<table{table_attrs}>{table_content}</table>'

        # Example: Add specific class if it's a function table (can be unreliable with regex)
        if '<th>Function</th>' in table_content and '<th>Target</th>' in table_content:
             processed_table = processed_table.replace('class="blueprint-table', 'class="blueprint-table function-table', 1)

        return processed_table

    # Replace tables using the function
    processed_html = re.sub(table_pattern, process_table_match, html, flags=re.IGNORECASE | re.DOTALL)
    return processed_html

# Register the filter with Flask
app.jinja_env.filters['markdown'] = blueprint_markdown

@app.route('/', methods=['GET', 'POST'])
def index():
    # --- ADD DEBUG PRINT 2 ---
    if request.method == 'POST':
        print(f"DEBUG: MAX_CONTENT_LENGTH during POST request: {app.config.get('MAX_CONTENT_LENGTH')}")
        try:
             print(f"DEBUG: Incoming request.content_length: {request.content_length}")
             content_length_header = request.headers.get('Content-Length')
             print(f"DEBUG: Incoming Content-Length header: {content_length_header}")
        except Exception as e:
             print(f"DEBUG: Could not get request length/header info: {e}")
    # -------------------------

    output = ""
    ai_output = ""
    error = ""
    stats_summary = ""
    raw_text = "" # Initialize raw_text

    # Default formats
    human_format_type = "enhanced_markdown"
    ai_format_type = "ai_readable"

    if request.method == 'POST':
        # --- REVISED MODIFICATION START ---
        # Avoid request.form entirely. Read directly from the input stream.
        try:
            # Get the content length from the header to avoid reading too much
            # Note: request.content_length might be None if chunked encoding is used,
            # but for simple form posts it should be present.
            content_length = request.content_length
            if content_length is None:
                # Try getting from header directly if attribute is None
                cl_header = request.headers.get('Content-Length')
                if cl_header:
                    content_length = int(cl_header)

            if content_length is None:
                 # Handle missing content length (e.g., chunked transfer) - might need limits
                 print("WARN: Content-Length header missing. Reading stream with potential risk.")
                 # Consider adding a hard limit here if needed:
                 # max_stream_read = 100 * 1024 * 1024 # 100MB read limit example
                 # raw_body = request.stream.read(max_stream_read)
                 raw_body = request.stream.read() # Read entire stream (use limit above if needed)
            elif content_length > app.config['MAX_CONTENT_LENGTH']:
                 # This check might be redundant if Werkzeug already did it, but belt-and-suspenders
                 raise ValueError("Content-Length exceeds MAX_CONTENT_LENGTH")
            else:
                 # Read exactly the specified number of bytes from the stream
                 raw_body = request.stream.read(content_length)
                 print(f"DEBUG: Read {len(raw_body)} bytes from request.stream")

            # Manually parse the raw body (assuming standard form encoding)
            decoded_body = raw_body.decode('utf-8')
            if decoded_body.startswith('blueprint_text='):
                from urllib.parse import unquote_plus
                raw_text = unquote_plus(decoded_body[len('blueprint_text='):])
                print("DEBUG: Read blueprint_text using request.stream and manual parsing")
            else:
                print("DEBUG: Could not manually parse blueprint_text from raw stream body")
                raw_text = ""
                error = "Unexpected request body format."

        except Exception as e:
             # Catch potential 413 raised during stream reading or other errors
             print(f"ERROR: Failed to read request stream data: {e}")
             # Check if the exception itself is the 413 error
             if "413" in str(e):
                  error = "Request Entity Too Large (error during stream read)."
             else:
                  error = f"Failed to read input data: {e}"
             raw_text = "" # Ensure raw_text is empty on error
        # --- REVISED MODIFICATION END ---

        # --- Original logic continues below ---
        if not error and not raw_text:
            if not error:
                 error = "Please paste some Blueprint text."
        elif not error:
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
                    
                    # Debug print to check if spans are present in the Python-generated output
                    print("DEBUG: Example spans in output:", output[:500])
                    if "<span class=" in output:
                        span_count = output.count("<span class=")
                        print(f"DEBUG: Found {span_count} spans in formatter output")
                    else:
                        print("DEBUG: NO SPANS found in formatter output - check node_formatter.py")
                    
                    # Clean any potential double-escaped entities
                    output = clean_html_entities(output)
                    
                    stats_summary = human_formatter.format_statistics() # Get stats from the formatter

                    # Get AI-readable output (JSON)
                    ai_formatter = get_formatter(ai_format_type, parser)
                    ai_output = ai_formatter.format_graph(input_filename="Pasted Blueprint")

                    # Debug prints
                    print(f"Output size: {len(output)}, AI output size: {len(ai_output)}")

            except ImportError as e:
                 print(f"Runtime Import Error: {e}", file=sys.stderr)
                 error = f"A required module could not be imported: {e}. Please check server logs."
            except Exception as e:
                 print(f"An unexpected error occurred during processing: {e}", file=sys.stderr)
                 import traceback
                 traceback.print_exc()
                 error = f"An unexpected error occurred: {e}. Check input or server logs for details."

            end_time = datetime.now()
            print(f"Processing finished at {end_time}. Duration: {end_time - start_time}")
    # --- GET request handling ---
    elif request.method == 'GET':
         # If you want to pre-populate from GET params (less common for large data)
         raw_text = request.args.get('blueprint_text', '')

    return render_template('index.html',
                          blueprint_output=output,
                          ai_output=ai_output, # Pass the AI output
                          error_message=error,
                          raw_blueprint_text=raw_text, # Pass raw_text back to template
                          stats_summary=stats_summary)

if __name__ == '__main__':
    # Use a secret key for session management if needed
    app.config['SECRET_KEY'] = os.urandom(24)
    # --- ADD DEBUG PRINT 3 ---
    print(f"DEBUG: Starting Flask app with MAX_CONTENT_LENGTH = {app.config.get('MAX_CONTENT_LENGTH')}")
    # -------------------------
    app.run(debug=True, host='0.0.0.0', port=5001)