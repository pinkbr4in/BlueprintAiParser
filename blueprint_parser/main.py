# --- START OF FILE main.py ---

import argparse
import sys
import os
import time
# --- Use relative imports within the package ---
from .parser import BlueprintParser
from .formatter.formatter import BlueprintFormatter # Import the main formatter
# Import debug flags directly from where they are defined
from . import parser as bp_parser_module
from . import nodes as bp_nodes_module
from .formatter import formatter as bp_formatter_module
from .formatter import node_formatter as bp_node_formatter_module
from .formatter import data_tracer as bp_data_tracer_module
from .formatter import path_tracer as bp_path_tracer_module

# Import the graph type detection function
from .unsupported_nodes import get_unsupported_graph_type

def main():
    """
    Main entry point for the Blueprint Parser application.
    Outputs formatted Markdown.
    """
    # Parse command line arguments
    arg_parser = argparse.ArgumentParser(
        description="Parse Unreal Engine Blueprint raw text into readable Markdown logic flow."
    )
    arg_parser.add_argument(
        "input_file",
        help="Path to the text file containing the copied Blueprint data."
    )
    arg_parser.add_argument(
        "-o", "--output",
        help="Optional output file path for Markdown. If not specified, results are printed to stdout."
    )
    arg_parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output during parsing and formatting."
    )
    args = arg_parser.parse_args()

    # --- Configure Debug Output ---
    original_stdout = sys.stdout
    class NullIO:
        def write(self, *args, **kwargs): pass
        def flush(self, *args, **kwargs): pass
    debug_stdout = NullIO()

    if args.debug:
        print("Debug mode enabled. Verbose output will be printed.")
        bp_nodes_module.ENABLE_NODE_DEBUG = False
        bp_parser_module.ENABLE_PARSER_DEBUG = False
        bp_node_formatter_module.ENABLE_NODE_FORMATTER_DEBUG = False
        bp_data_tracer_module.ENABLE_TRACER_DEBUG = False
        bp_path_tracer_module.ENABLE_PATH_TRACER_DEBUG = False
    else:
        sys.stdout = debug_stdout # Suppress internal prints if not debug

    # --- Read Input File ---
    try:
        with open(args.input_file, 'r', encoding='utf-8') as f:
            blueprint_text = f.read()
        input_filename = os.path.basename(args.input_file) # Get filename for header
    except FileNotFoundError:
        sys.stdout = original_stdout
        print(f"Error: Input file not found: {args.input_file}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        sys.stdout = original_stdout
        print(f"Error reading file: {e}", file=sys.stderr)
        sys.exit(1)

    # --- Parsing Phase ---
    start_time = time.time()
    nodes = {}
    parser = BlueprintParser()

    try:
        print("Parsing Blueprint text...") # Captured if not debug
        nodes = parser.parse(blueprint_text)
        print(f"Parsed {len(nodes)} nodes.")
    except Exception as e:
         sys.stdout = original_stdout
         print(f"\nError during parsing: {e}", file=sys.stderr)
         import traceback
         traceback.print_exc()
         sys.exit(1)
    finally:
        if not args.debug: sys.stdout = original_stdout # Restore stdout

    if not nodes:
        print("Parsing resulted in no nodes.")
        sys.exit(0)

    parse_time = time.time() - start_time
    if args.debug: print(f"Parsing completed in {parse_time:.2f} seconds")

    # --- Unsupported Graph Type Detection ---
    # (Keep this section largely the same, but maybe output basic info as Markdown)
    is_unsupported_graph = False
    detected_unsupported_type = "Unknown Specialized"
    if nodes:
        for node in nodes.values():
            ue_class_for_check = node.ue_class if node.ue_class else ""
            if node.node_type in ["Knot", "Comment", "NiagaraReroute"] or not ue_class_for_check:
                 continue
            unsupported_type = get_unsupported_graph_type(ue_class_for_check)
            if unsupported_type:
                is_unsupported_graph = True
                detected_unsupported_type = unsupported_type
                print(f"Detected unsupported node type: {node.ue_class} ({unsupported_type})")
                break

    if is_unsupported_graph:
        # Output basic info as Markdown
        output = f"""
# Unsupported Graph Type Detected: {input_filename}

**Graph Type:** {detected_unsupported_type}

This tool currently only supports standard Blueprint logic graphs (Event Graphs, Functions, Macros).
The detected graph type ({detected_unsupported_type}) is not supported for detailed formatting.

- **Total Nodes Detected:** {len(nodes)}
"""
        if args.output:
            try:
                with open(args.output, 'w', encoding='utf-8') as f: f.write(output)
                print(f"Unsupported graph type detected. Basic info written to {args.output}")
            except Exception as e: print(f"Error writing unsupported graph info: {e}", file=sys.stderr)
        else:
            print(output)
        sys.exit(0)

    # --- Formatting Phase (Only for supported graphs) ---
    format_start_time = time.time()
    formatted_output = "[Formatting Error Occurred]"

    if not args.debug: sys.stdout = debug_stdout # Redirect again

    try:
        print("\nFormatting execution paths...") # Captured if not debug
        formatter = BlueprintFormatter(nodes)
        # Pass input filename to formatter
        formatted_output = formatter.format_graph(input_filename=input_filename)
    except Exception as e:
        sys.stdout = original_stdout # Restore before error
        print(f"\nError during formatting: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        if not args.debug: sys.stdout = original_stdout # Always restore

    format_time = time.time() - format_start_time
    total_time = time.time() - start_time

    # Add performance info as a comment in debug mode
    if args.debug:
        performance_info = f"""
```text
# --- Performance Information ---
# Parsing time: {parse_time:.2f} seconds
# Formatting time: {format_time:.2f} seconds
# Total processing time: {total_time:.2f} seconds
# Nodes Processed: {len(nodes)}
```
"""
        formatted_output += "\n" + performance_info

    # --- Output Result ---
    if args.output:
        try:
            with open(args.output, 'w', encoding='utf-8') as f:
                f.write(formatted_output)
            print(f"Formatted Blueprint Markdown written to {args.output}")
        except Exception as e:
            print(f"Error writing output file: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        # Print directly to stdout (which is now original_stdout)
        print("\n" + "="*20 + " Formatted Blueprint Markdown " + "="*20 + "\n")
        print(formatted_output)
        print("\n" + "="*20 + " End of Markdown " + "="*20 + "\n")

if __name__ == "__main__":
    main()
# --- END OF FILE main.py ---