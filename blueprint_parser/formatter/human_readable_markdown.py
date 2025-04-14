# blueprint_parser/formatter/human_readable_markdown.py

import re
import sys
from datetime import datetime
from typing import Dict, Optional, Set, Any, List

# Ensure necessary imports from the package are present
from ..parser import BlueprintParser
from ..nodes import (
    Node, EdGraphNode_Comment, K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction,
    K2Node_InputAction, K2Node_InputAxisEvent, K2Node_InputKey, K2Node_InputTouch,
    K2Node_InputAxisKeyEvent, K2Node_InputDebugKey, K2Node_FunctionEntry, K2Node_VariableSet,
    K2Node_CallFunction, K2Node_MacroInstance # Add other specific nodes if needed by formatters
)
# Import BaseFormatter from the correct relative path
from .formatter import BaseFormatter

# --- Helper Function to Strip HTML ---
def strip_html_tags(html_string):
    """Removes HTML tags from a string."""
    if not isinstance(html_string, str):
        return str(html_string) # Return string representation of non-strings
    # Regex to remove anything that looks like an HTML tag <...>
    return re.sub(r'<[^>]+>', '', html_string)
# ------------------------------------

class EnhancedMarkdownFormatter(BaseFormatter):
    """Formats blueprint data into enhanced human-readable Markdown using tree structure."""

    def format_graph(self, input_filename: Optional[str] = None) -> str:
        """Formats the entire blueprint graph into enhanced human-readable Markdown."""
        output_lines = []
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        title = f"Pasted Blueprint" if input_filename == "Pasted Blueprint" else f"{input_filename}"

        # --- Header ---
        output_lines.append(f"# Blueprint Analysis")
        output_lines.append(f"**Source:** {title}")
        output_lines.append(f"**Generated:** {timestamp}")

        # --- Structure Summary ---
        stats = self.parser.stats
        total_nodes = stats.get('total_nodes', 0)
        comment_count = stats.get('comment_count', 0)
        functional_nodes = total_nodes - comment_count
        links_resolved = stats.get('links_resolved', 0)
        links_unresolved = stats.get('links_unresolved', 0)

        output_lines.append(f"\n## Structure Summary")
        output_lines.append(f"- **Nodes:** {total_nodes} total ({functional_nodes} functional, {comment_count} comment)")
        output_lines.append(f"- **Connections:** {links_resolved} resolved, {links_unresolved} unresolved")

        # --- Clear Caches and Reset Global State ---
        # Ensure data_tracer exists before clearing cache
        if hasattr(self, 'data_tracer') and self.data_tracer:
            self.data_tracer.clear_cache()
        else:
             # Fallback or warning if data_tracer wasn't initialized properly (shouldn't happen with BaseFormatter structure)
             print("Warning: Data tracer not available for cache clear.", file=sys.stderr)

        processed_globally = set()  # Track nodes processed across all paths

        # --- Find Execution Start Points ---
        start_nodes = self._get_execution_start_nodes() # Inherited from BaseFormatter
        entry_points_count = len(start_nodes)
        output_lines.append(f"- **Entry Points:** {entry_points_count}")
        output_lines.append("\n---\n")

        # --- Execution Flow Section ---
        # This section correctly uses path_tracer which uses node_formatter, preserving HTML spans
        output_lines.append("## Execution Flow\n")

        if not start_nodes:
            output_lines.append("**Warning:** No execution entry points found.")
        else:
            for i, start_node in enumerate(start_nodes):
                entry_point_id = f"entry-point-{i+1}"
                # node_formatter generates descriptions WITH spans
                start_node_header_desc = self.node_formatter._get_formatter_func(start_node)(start_node, set())
                # Clean up bolding specifically for the header text
                start_node_header_desc = start_node_header_desc.replace("**Event**", "Event").replace("**Custom Event**", "Custom Event").replace("**Function Entry**", "Function Entry").replace("**Input Action**", "Input Action")
                output_lines.append(f"### {start_node_header_desc} <a id=\"{entry_point_id}\"></a>") # Header keeps spans
                output_lines.append("```blueprint") # Start code block where spans are needed
                path_specific_visited = set()
                if not start_node.is_pure():
                    processed_globally.add(start_node.guid)
                # path_tracer generates lines WITH spans
                path_lines = self.path_tracer.trace_path(
                    start_node=start_node,
                    processed_guids_in_path=path_specific_visited,
                    processed_globally=processed_globally,
                    indent_prefix="",
                    is_last_segment=True
                )
                output_lines.extend(path_lines)
                output_lines.append("```") # End code block
                output_lines.append("\n---\n") # Separator

        # --- Summaries Section ---
        # Call extraction functions which STRIP HTML internally now
        all_variable_ops = self.extract_variable_operations(processed_globally)
        all_function_calls = self.extract_function_calls(processed_globally)

        # Format Variable Summary Table (using plain text values)
        if all_variable_ops:
            output_lines.append("## Variable Operations Summary")
            output_lines.append("*(Variables modified during execution)*\n")
            output_lines.append("| Variable | Type | Value Set |")
            output_lines.append("|----------|------|-----------|")
            for var_name in sorted(all_variable_ops.keys()):
                op_data = all_variable_ops[var_name]
                var_type = f"`{op_data.get('type', '?')}`"
                # Values in op_data['values'] are already plain text
                unique_values = sorted(list(set(op_data['values'])))
                # Format values for table (smart backticks)
                formatted_values = []
                for v in unique_values:
                    v_stripped = v.strip()
                    if any(c in v_stripped for c in ' ()+-*/%') or v_stripped == '<?>' or '[Error]' in v_stripped or v_stripped.startswith('ResultOf'):
                         formatted_values.append(v_stripped)
                    else:
                         formatted_values.append(f"`{v_stripped}`")
                value_str_for_table = ", ".join(formatted_values) if formatted_values else '?'
                output_lines.append(f"| `{var_name}` | {var_type} | {value_str_for_table} |")
            output_lines.append("\n---\n")

        # Format Function Call Summary Table (LISTING INDIVIDUAL CALLS with plain text)
        if all_function_calls:
            output_lines.append("## Function Call Summary")
            output_lines.append("*(Individual function calls during execution)*\n")
            output_lines.append("| Function | Target | Parameters Called With | Latent |")
            output_lines.append("|----------|--------|------------------------|--------|")

            # Create a flat list of all individual calls
            flat_call_list = []
            for func_name, call_data in all_function_calls.items():
                for call_info in call_data['calls']:
                    call_info['function_name'] = func_name # Add name for sorting/display
                    flat_call_list.append(call_info)

            # Optional: Sort the list (e.g., by function name)
            flat_call_list.sort(key=lambda call: call.get('function_name', ''))

            # Iterate through each individual call
            for call in flat_call_list:
                func_name = call.get('function_name', 'UnknownFunction')
                params = call.get('params', {}) # Contains plain values
                target_plain = call.get('target', '`self`') # Contains plain value

                # Format parameters (smart backticks)
                formatted_params = []
                for p, v in sorted(params.items()):
                     v_stripped = v.strip()
                     if any(c in v_stripped for c in ' ()+-*/%') or v_stripped == '<?>' or '[Error]' in v_stripped or v_stripped.startswith('ResultOf') or v_stripped.startswith('Default__'):
                          formatted_params.append(f"{p}={v_stripped}")
                     else:
                          formatted_params.append(f"{p}=`{v_stripped}`")
                param_str = ", ".join(formatted_params) if formatted_params else "-"

                # Format target (smart backticks)
                target_for_table = f"`{target_plain}`" if not any(c in target_plain for c in ' ()+-*/%') and target_plain != 'self' else target_plain

                latent_str = "Yes" if call.get('is_latent', False) else "No"

                # Output the table row for this specific call
                output_lines.append(f"| `{func_name}` | {target_for_table} | {param_str} | {latent_str} |")

            output_lines.append("\n---\n")

        # --- Unconnected Executable Nodes Section (Unchanged - uses node_formatter with spans) ---
        all_parsed_non_comment_guids = {n.guid for n in self.parser.nodes.values()
                                         if not isinstance(n, EdGraphNode_Comment)}
        untouched_guids = all_parsed_non_comment_guids - processed_globally
        unconnected_executable_nodes = []
        if untouched_guids:
             for guid in sorted(list(untouched_guids)):
                node = self.parser.get_node_by_guid(guid)
                if node and not node.is_pure():
                    input_exec_pin = node.get_execution_input_pin()
                    is_potential_start = isinstance(node, (K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction, K2Node_InputAction, K2Node_InputAxisEvent, K2Node_InputKey, K2Node_InputTouch, K2Node_InputAxisKeyEvent, K2Node_InputDebugKey, K2Node_FunctionEntry))
                    if (input_exec_pin and not input_exec_pin.source_pin_for) or \
                       (is_potential_start and (not input_exec_pin or not input_exec_pin.source_pin_for)):
                           unconnected_executable_nodes.append(node)

        if unconnected_executable_nodes:
            output_lines.append("## Unconnected Executable Blocks")
            output_lines.append("*(Found executable nodes/sequences not reached by main entry points)*")
            output_lines.append("")
            for node in unconnected_executable_nodes:
                # This call correctly gets the description WITH spans
                node_desc_str = self.node_formatter._get_formatter_func(node)(node, set())
                output_lines.append(f"- {node_desc_str}") # Output keeps spans
            output_lines.append("\n---\n")

        # --- Final Join ---
        final_output_string = '\n'.join(output_lines)
        return final_output_string

    # --- extract_variable_operations (MODIFIED - USES HELPER) ---
    def extract_variable_operations(self, processed_nodes_guids: Set[str]) -> Dict[str, Dict]:
        """Extracts variable operations, storing PLAIN TEXT values."""
        variables = {}
        for guid in processed_nodes_guids:
            node = self.parser.get_node_by_guid(guid)
            if isinstance(node, K2Node_VariableSet) and node.variable_name:
                var_name = node.variable_name
                value_pin = node.get_value_input_pin()
                value_str_with_spans = self.data_tracer.trace_pin_value(value_pin, visited_pins=set()) if value_pin else "<?>"
                # STRIP the spans for storage
                plain_value_str = strip_html_tags(value_str_with_spans) # <-- USE HELPER

                if var_name not in variables:
                    var_type_sig = node.variable_type or (value_pin.get_type_signature() if value_pin else None)
                    variables[var_name] = {'type': var_type_sig or '?', 'values': []}
                # Store the PLAIN text value
                variables[var_name]['values'].append(plain_value_str)
        return variables

    # --- extract_function_calls (MODIFIED - USES HELPER) ---
    def extract_function_calls(self, processed_nodes_guids: Set[str]) -> Dict[str, Dict]:
        """Extracts function calls, storing PLAIN TEXT target and params."""
        functions = {}
        for guid in processed_nodes_guids:
            node = self.parser.get_node_by_guid(guid)
            if isinstance(node, K2Node_CallFunction) and node.function_name:
                func_name = node.function_name
                params_plain = {}
                target_pin = node.get_target_pin()
                target_str_with_spans = self.data_tracer._trace_target_pin(target_pin, set()) if target_pin else "`self`"
                # STRIP spans for storage
                plain_target_str = strip_html_tags(target_str_with_spans) # <-- USE HELPER

                for pin in node.get_input_pins(exclude_exec=True):
                    if pin.name and pin.name.lower() not in ['self', 'target', 'worldcontextobject', '__worldcontext', 'latentinfo']:
                        val_with_spans = self.data_tracer.trace_pin_value(pin, visited_pins=set())
                        # STRIP spans for storage
                        plain_val = strip_html_tags(val_with_spans) # <-- USE HELPER
                        params_plain[pin.name] = plain_val # Store plain text

                # Store call info with PLAIN text values
                call_info = {
                    'target': plain_target_str,
                    'params': params_plain,
                    'is_latent': node.is_latent
                }
                if func_name not in functions:
                    functions[func_name] = {'calls': []}
                functions[func_name]['calls'].append(call_info)
        return functions