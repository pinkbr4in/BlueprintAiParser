# blueprint_parser/formatter/human_readable_markdown.py

import sys
from datetime import datetime
from typing import Dict, Optional, Set, Any, List

from ..parser import BlueprintParser
from ..nodes import (
    Node, EdGraphNode_Comment, K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction,
    K2Node_InputAction, K2Node_InputAxisEvent, K2Node_InputKey, K2Node_InputTouch,
    K2Node_InputAxisKeyEvent, K2Node_InputDebugKey, K2Node_FunctionEntry, K2Node_VariableSet,
    K2Node_CallFunction, K2Node_MacroInstance
)

from .formatter import BaseFormatter

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
        self.data_tracer.clear_cache()
        processed_globally = set()  # Track nodes processed across all paths

        # --- Find Execution Start Points ---
        start_nodes = self._get_execution_start_nodes()
        entry_points_count = len(start_nodes)
        output_lines.append(f"- **Entry Points:** {entry_points_count}")
        output_lines.append("\n---\n")

        # --- Execution Flow Section ---
        output_lines.append("## Execution Flow\n")

        if not start_nodes:
            output_lines.append("**Warning:** No execution entry points found.")
        else:
            # --- Format Each Entry Point ---
            for i, start_node in enumerate(start_nodes):
                entry_point_id = f"entry-point-{i+1}"

                # Get formatted description of the start node itself
                start_node_header_desc = self.node_formatter._get_formatter_func(start_node)(start_node, set())
                start_node_header_desc = start_node_header_desc.replace("**Event**", "Event").replace("**Custom Event**", "Custom Event").replace("**Function Entry**", "Function Entry").replace("**Input Action**", "Input Action")

                # Add header for entry point with anchor
                output_lines.append(f"### {start_node_header_desc} <a id=\"{entry_point_id}\"></a>")

                # --- REMOVED direct comment printing here - handled by PathTracer ---
                # start_node_comment = self.comment_handler.get_comment(start_node.guid)
                # if start_node_comment:
                #    ... (removed block)

                # --- Trace Path ---
                output_lines.append("```blueprint") # Start blueprint code block

                # --- CORRECTION HERE ---
                # Initialize path_specific_visited as EMPTY.
                # trace_path will add the start_node itself.
                path_specific_visited = set()
                # -----------------------

                # Add start node to global processed set *if* it's executable
                # (We still need to do this here, before calling trace_path)
                if not start_node.is_pure():
                    processed_globally.add(start_node.guid)

                # Call trace_path with the *empty* path-specific set
                path_lines = self.path_tracer.trace_path(
                    start_node=start_node,
                    processed_guids_in_path=path_specific_visited, # Pass the empty set directly
                    processed_globally=processed_globally,
                    indent_prefix="",
                    is_last_segment=True
                )

                # --- Append the generated path lines ---
                output_lines.extend(path_lines)
                # --- End Append ---

                output_lines.append("```") # End blueprint code block
                output_lines.append("\n---\n") # Separator between entry points

        # --- Summaries Section (Unchanged) ---
        all_variable_ops = self.extract_variable_operations(processed_globally)
        all_function_calls = self.extract_function_calls(processed_globally)

        if all_variable_ops:
            output_lines.append("## Variable Operations Summary")
            output_lines.append("*(Variables modified during execution)*\n")
            output_lines.append("| Variable | Type | Value Set |")
            output_lines.append("|----------|------|-----------|")
            for var_name in sorted(all_variable_ops.keys()):
                op_data = all_variable_ops[var_name]
                var_type = f"`{op_data.get('type', '?')}`"
                # Show only unique values set for summary
                unique_values = sorted(list(set(op_data['values'])))
                value_str = ", ".join(f"`{v}`" for v in unique_values) if unique_values else '?'
                output_lines.append(f"| `{var_name}` | {var_type} | {value_str} |")
            output_lines.append("\n---\n")

        if all_function_calls:
            output_lines.append("## Function Call Summary")
            output_lines.append("*(Functions called during execution)*\n")
            output_lines.append("| Function | Target | Parameters Called With | Latent |")
            output_lines.append("|----------|--------|------------------------|--------|")
            # Aggregate calls for summary
            for func_name in sorted(all_function_calls.keys()):
                call_data = all_function_calls[func_name]
                # For simplicity, show params from the first call in summary
                first_call = call_data['calls'][0]
                params = first_call['params']
                param_str = ", ".join(f"{p}=`{v}`" for p, v in params.items()) if params else "-"
                target_str = first_call['target']
                latent_str = "Yes" if first_call['is_latent'] else "No"
                call_count_str = f" (x{len(call_data['calls'])})" if len(call_data['calls']) > 1 else ""
                output_lines.append(f"| `{func_name}`{call_count_str} | `{target_str}` | {param_str} | {latent_str} |")
            output_lines.append("\n---\n")


        # --- Unconnected Executable Nodes Section (Unchanged) ---
        all_parsed_non_comment_guids = {n.guid for n in self.parser.nodes.values()
                                         if not isinstance(n, EdGraphNode_Comment)}
        untouched_guids = all_parsed_non_comment_guids - processed_globally

        unconnected_executable_nodes = []
        if untouched_guids:
             for guid in sorted(list(untouched_guids)):
                node = self.parser.get_node_by_guid(guid)
                # Add check for nodes that *can* start execution but weren't reached
                if node and not node.is_pure():
                    input_exec_pin = node.get_execution_input_pin()
                    is_potential_start = isinstance(node, (K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction, K2Node_InputAction, K2Node_InputAxisEvent, K2Node_InputKey, K2Node_InputTouch, K2Node_InputAxisKeyEvent, K2Node_InputDebugKey, K2Node_FunctionEntry))
                    # Node is unconnected if it has no input exec source OR it's a potential start node type without an input exec source
                    if (input_exec_pin and not input_exec_pin.source_pin_for) or \
                       (is_potential_start and (not input_exec_pin or not input_exec_pin.source_pin_for)):
                           unconnected_executable_nodes.append(node)


        if unconnected_executable_nodes:
            output_lines.append("## Unconnected Executable Blocks")
            output_lines.append("*(Found executable nodes/sequences not reached by main entry points)*")
            output_lines.append("")
            for node in unconnected_executable_nodes:
                node_desc_str = self.node_formatter._get_formatter_func(node)(node, set())
                # Add a simple prefix for unconnected blocks
                output_lines.append(f"- {node_desc_str}")
                # Optionally, trace their paths briefly if desired
                # path_lines = self.path_tracer.trace_path(node, {node.guid}, processed_globally, "  ", True)
                # output_lines.extend([f"  {line}" for line in path_lines]) # Indent unconnected paths
            output_lines.append("\n---\n")

        final_output_string = '\n'.join(output_lines)
        return final_output_string

    # --- extract_variable_operations and extract_function_calls remain unchanged ---
    def extract_variable_operations(self, processed_nodes_guids: Set[str]) -> Dict[str, Dict]:
        """Extracts variable operations from ALL processed nodes."""
        variables = {} # Key: var_name, Value: {'type': str, 'values': list[str]}
        for guid in processed_nodes_guids:
            node = self.parser.get_node_by_guid(guid)
            if isinstance(node, K2Node_VariableSet) and node.variable_name:
                var_name = node.variable_name
                value_pin = node.get_value_input_pin()
                # Ensure data tracer has a fresh set for each value trace
                value_str = self.data_tracer.trace_pin_value(value_pin, visited_pins=set()) if value_pin else "<?>"

                if var_name not in variables:
                    var_type_sig = node.variable_type or (value_pin.get_type_signature() if value_pin else None)
                    variables[var_name] = {'type': var_type_sig or '?', 'values': []}
                variables[var_name]['values'].append(value_str) # Record all values set

        return variables

    def extract_function_calls(self, processed_nodes_guids: Set[str]) -> Dict[str, Dict]:
        """Extracts function calls from ALL processed nodes."""
        functions = {} # Key: func_name, Value: {'calls': list[dict]}
        for guid in processed_nodes_guids:
            node = self.parser.get_node_by_guid(guid)
            if isinstance(node, K2Node_CallFunction) and node.function_name:
                func_name = node.function_name
                params = {}
                target_pin = node.get_target_pin()
                # Use a fresh set for tracing target each time
                target_str = self.data_tracer._trace_target_pin(target_pin, set()) if target_pin else "`self`"

                for pin in node.get_input_pins(exclude_exec=True):
                    if pin.name and pin.name.lower() not in ['self', 'target', 'worldcontextobject', '__worldcontext', 'latentinfo']:
                        # Use a fresh set for tracing each parameter
                        val = self.data_tracer.trace_pin_value(pin, visited_pins=set())
                        params[pin.name] = val

                call_info = {
                    'target': target_str,
                    'params': params,
                    'is_latent': node.is_latent
                }

                if func_name not in functions:
                    functions[func_name] = {'calls': []}
                functions[func_name]['calls'].append(call_info)

        return functions