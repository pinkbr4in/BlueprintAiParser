# blueprint_parser/formatter/human_readable_markdown.py

import re
import sys
from datetime import datetime
from typing import Dict, Optional, Set, Any, List

# --- Use relative imports ---
from ..parser import BlueprintParser
from ..nodes import (
    Node, EdGraphNode_Comment, K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction,
    K2Node_InputAction, K2Node_InputAxisEvent, K2Node_InputKey, K2Node_InputTouch,
    K2Node_InputAxisKeyEvent, K2Node_InputDebugKey, K2Node_FunctionEntry, K2Node_VariableSet,
    K2Node_CallFunction, K2Node_MacroInstance,
    # --- ADDED missing imports for is_orphan_start check ---
    K2Node_ComponentBoundEvent, K2Node_ActorBoundEvent
    # --- END ADDED imports ---
)
# Import BaseFormatter from the correct relative path
from .formatter import BaseFormatter
# --- CORRECTED IMPORT PATH for strip_html_tags ---
# Use '..' to go up one directory level from 'formatter' to 'blueprint_parser'
from ..utils import strip_html_tags
# --- END CORRECTION ---

# --- REMOVED Local Definition (now imported correctly) ---
# def strip_html_tags(html_string): ...

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
             # Use slightly more specific warning message
             print("Warning (EnhancedMarkdownFormatter): Data tracer not available for cache clear.", file=sys.stderr)

        # --- MODIFIED START: Apply changes from the request ---
        processed_globally = set() # Track nodes processed across all paths

        # --- Find Execution Start Points (using updated logic) ---
        start_nodes = self._get_execution_start_nodes() # Inherited from BaseFormatter
        entry_points_count = len(start_nodes)
        # Determine if we are using fallback orphan nodes
        is_orphan_start = not any(isinstance(n, (
            K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction, K2Node_InputAction,
            K2Node_InputAxisEvent, K2Node_InputKey, K2Node_InputTouch, K2Node_InputAxisKeyEvent,
            K2Node_InputDebugKey, K2Node_FunctionEntry, K2Node_ComponentBoundEvent, K2Node_ActorBoundEvent
        )) for n in start_nodes)

        # --- Updated Summary Output ---
        output_lines.append(f"- **Entry Points Found:** {entry_points_count}") # Changed text
        if is_orphan_start and entry_points_count > 0:
             # Added warning for orphan/inferred starts
             output_lines.append("  *(Note: No standard Event/Input found; showing execution starting from unlinked nodes)*")
        output_lines.append("\n---\n")

        # --- Execution Flow Section ---
        output_lines.append("## Execution Flow\n")

        if not start_nodes:
            # Updated warning message for no starting points
            output_lines.append("**Warning:** No execution entry points or starting nodes found in the pasted snippet.")
        else:
            for i, start_node in enumerate(start_nodes):
                entry_point_id = f"entry-point-{i+1}"
                # node_formatter generates descriptions WITH spans
                start_node_header_desc_with_spans = self.node_formatter._get_formatter_func(start_node)(start_node, set())
                # Clean up common bolding and add line break before args specifically for the header text
                start_node_header_text = start_node_header_desc_with_spans.replace("**Event**", "Event").replace("**Custom Event**", "Custom Event").replace("**Function Entry**", "Function Entry").replace("**Input Action**", "Input Action").replace("Args:", "<br>Args:") # Add line break before args
                # Indicate if it's an inferred start point
                start_prefix = "[Inferred Start] " if is_orphan_start else "" # Added prefix logic
                output_lines.append(f"### {start_prefix}{start_node_header_text} <a id=\"{entry_point_id}\"></a>") # Header includes prefix and keeps spans
                output_lines.append("```blueprint") # Start code block where spans are needed
                path_specific_visited = set()
                if not start_node.is_pure():
                    processed_globally.add(start_node.guid) # Track processed non-pure nodes globally
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
        # --- MODIFIED END ---

        # --- Summaries Section ---
        # Call extraction functions which STRIP HTML internally now (using imported helper)
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
                    # Apply backticks unless it's complex, error, result, etc.
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
                    # Apply backticks unless it's complex, error, result, default object etc.
                    if any(c in v_stripped for c in ' ()+-*/%') or v_stripped == '<?>' or '[Error]' in v_stripped or v_stripped.startswith('ResultOf') or v_stripped.startswith('Default__'):
                        formatted_params.append(f"{p}={v_stripped}")
                    else:
                        formatted_params.append(f"{p}=`{v_stripped}`")
                param_str = ", ".join(formatted_params) if formatted_params else "-"

                # Format target (smart backticks) - Apply unless complex or 'self'
                target_for_table = f"`{target_plain}`" if not any(c in target_plain for c in ' ()+-*/%') and target_plain != 'self' and not target_plain.startswith('ResultOf') else target_plain

                latent_str = "Yes" if call.get('is_latent', False) else "No"

                # Output the table row for this specific call
                output_lines.append(f"| `{func_name}` | {target_for_table} | {param_str} | {latent_str} |")

            output_lines.append("\n---\n")

        # --- Unconnected Executable Nodes Section ---
        # This section should now mostly remain empty if orphans are treated as entry points,
        # but the logic is kept for completeness in case some nodes are truly unreachable.
        all_parsed_non_comment_guids = {n.guid for n in self.parser.nodes.values()
                                        if not isinstance(n, EdGraphNode_Comment)}
        untouched_guids = all_parsed_non_comment_guids - processed_globally
        unconnected_executable_nodes = []
        if untouched_guids:
             # Refined logic to find unconnected nodes *not* used as entry points
             for guid in sorted(list(untouched_guids)):
                 node = self.parser.get_node_by_guid(guid)
                 # Include only if it's executable and wasn't processed
                 if node and not node.is_pure():
                    # No need to check if it *looks* like a start point here,
                    # as the main loop handles that. We just list anything executable left over.
                     unconnected_executable_nodes.append(node)

        if unconnected_executable_nodes:
            output_lines.append("## Unconnected Executable Blocks")
            output_lines.append("*(Found executable nodes/sequences not reached by main entry points)*")
            output_lines.append("")
            for node in unconnected_executable_nodes:
                # --- Get description WITH spans, then STRIP HTML for list output ---
                # Use format_node which often returns the string and a boolean (is_pure)
                format_result = self.node_formatter.format_node(node, "", set())
                node_desc_with_spans = format_result[0] if isinstance(format_result, tuple) and len(format_result) > 0 else (format_result if isinstance(format_result, str) else None)

                # Strip HTML for the list representation
                node_desc_plain = strip_html_tags(node_desc_with_spans) if node_desc_with_spans else f"[Could not format node {node.guid[:4]}]"
                output_lines.append(f"- {node_desc_plain}") # Use plain text in the list
            output_lines.append("\n---\n")

        # --- Final Join ---
        final_output_string = '\n'.join(output_lines)
        return final_output_string

    # --- extract_variable_operations (Uses imported strip_html_tags) ---
    def extract_variable_operations(self, processed_nodes_guids: Set[str]) -> Dict[str, Dict]:
        """Extracts variable operations, storing PLAIN TEXT values."""
        variables = {}
        for guid in processed_nodes_guids:
            node = self.parser.get_node_by_guid(guid)
            if isinstance(node, K2Node_VariableSet) and node.variable_name:
                var_name = node.variable_name
                value_pin = node.get_value_input_pin()
                value_str_with_spans = self.data_tracer.trace_pin_value(value_pin, visited_pins=set()) if value_pin else "<?>"
                # STRIP the spans for storage using the imported helper
                plain_value_str = strip_html_tags(value_str_with_spans) # <-- USES IMPORTED HELPER

                if var_name not in variables:
                    var_type_sig = node.variable_type or (value_pin.get_type_signature() if value_pin else None)
                    variables[var_name] = {'type': var_type_sig or '?', 'values': []}
                # Store the PLAIN text value
                variables[var_name]['values'].append(plain_value_str)
        return variables

    # --- extract_function_calls (Uses imported strip_html_tags) ---
    def extract_function_calls(self, processed_nodes_guids: Set[str]) -> Dict[str, Dict]:
        """Extracts function calls, storing PLAIN TEXT target and params."""
        functions = {}
        for guid in processed_nodes_guids:
            node = self.parser.get_node_by_guid(guid)
            if isinstance(node, (K2Node_CallFunction, K2Node_MacroInstance)) and node.function_name: # Also check Macros
                func_name = node.function_name
                params_plain = {}
                target_pin = node.get_target_pin()
                target_str_with_spans = self.data_tracer._trace_target_pin(target_pin, set()) if target_pin else "`self`"
                # STRIP spans for storage using the imported helper
                plain_target_str = strip_html_tags(target_str_with_spans) # <-- USES IMPORTED HELPER

                for pin in node.get_input_pins(exclude_exec=True):
                    # Updated exclusion list
                    if pin.name and pin.name.lower() not in ['self', 'target', 'worldcontextobject', '__worldcontext', 'latentinfo', 'then']:
                        val_with_spans = self.data_tracer.trace_pin_value(pin, visited_pins=set())
                        # STRIP spans for storage using the imported helper
                        plain_val = strip_html_tags(val_with_spans) # <-- USES IMPORTED HELPER
                        params_plain[pin.name] = plain_val # Store plain text

                # Store call info with PLAIN text values
                call_info = {
                    'target': plain_target_str,
                    'params': params_plain,
                    'is_latent': getattr(node, 'is_latent', False) # Use getattr for safety (Macros don't have it)
                }
                if func_name not in functions:
                    functions[func_name] = {'calls': []}
                functions[func_name]['calls'].append(call_info)
        return functions

# --- END OF FILE blueprint_parser/formatter/human_readable_markdown.py ---