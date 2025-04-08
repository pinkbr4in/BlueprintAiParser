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
    """Formats blueprint data into enhanced human-readable Markdown."""

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

                # Add comment if available, using blockquote
                start_node_comment = self.comment_handler.get_comment(start_node.guid)
                if start_node_comment:
                    comment_lines = start_node_comment.strip().split('\n')
                    for c_line in comment_lines:
                        output_lines.append(f"> {c_line}")
                    output_lines.append("") # Blank line after comment

                # --- Trace Path ---
                output_lines.append("```blueprint") # Start blueprint code block

                path_specific_visited = {start_node.guid}
                if not start_node.is_pure():
                    processed_globally.add(start_node.guid)

                first_exec_output = start_node.get_execution_output_pin()
                node_to_trace_first = None
                if first_exec_output and first_exec_output.linked_pins:
                    target_pin = first_exec_output.linked_pins[0]
                    node_to_trace_first = self.parser.get_node_by_guid(target_pin.node_guid)

                lines_to_add = []
                if node_to_trace_first:
                    path_lines = self.path_tracer.trace_path(
                        start_node=node_to_trace_first,
                        processed_guids_in_path=path_specific_visited.copy(),
                        processed_globally=processed_globally,
                        indent=""
                    )
                    lines_to_add.extend(path_lines) # Use extend for list of lines
                elif first_exec_output:
                    lines_to_add.append(f"{self.path_tracer.exec_prefix}[Path ends: Pin '{first_exec_output.name}' unlinked]")
                else:
                    lines_to_add.append(f"{self.path_tracer.exec_prefix}[Path ends: No execution output]")

                # --- Append the generated path lines ---
                output_lines.extend(lines_to_add)
                # --- End Append ---

                output_lines.append("```") # End blueprint code block
                output_lines.append("\n---\n") # Separator between entry points

        # --- Summaries Section (Moved outside the loop) ---
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
                value_str = op_data['values'][0] if op_data['values'] else '?'
                output_lines.append(f"| `{var_name}` | {var_type} | `{value_str}` |")
            output_lines.append("\n---\n")

        if all_function_calls:
            output_lines.append("## Function Call Summary")
            output_lines.append("*(Functions called during execution)*\n")
            output_lines.append("| Function | Target | Parameters Called With | Latent |")
            output_lines.append("|----------|--------|------------------------|--------|")
            for func_name in sorted(all_function_calls.keys()):
                call_data = all_function_calls[func_name]
                params = call_data['calls'][0]['params']
                param_str = ", ".join(f"{p}=`{v}`" for p, v in params.items()) if params else "-"
                target_str = call_data['calls'][0]['target']
                latent_str = "Yes" if call_data['calls'][0]['is_latent'] else "No"
                output_lines.append(f"| `{func_name}` | `{target_str}` | {param_str} | {latent_str} |")
            output_lines.append("\n---\n")

        # --- Unconnected Executable Nodes Section ---
        all_parsed_non_comment_guids = {n.guid for n in self.parser.nodes.values()
                                         if not isinstance(n, EdGraphNode_Comment)}
        untouched_guids = all_parsed_non_comment_guids - processed_globally

        unconnected_executable_nodes = []
        if untouched_guids:
             for guid in sorted(list(untouched_guids)):
                node = self.parser.get_node_by_guid(guid)
                if node and not node.is_pure():
                    input_exec_pin = node.get_execution_input_pin()
                    if (input_exec_pin and not input_exec_pin.source_pin_for) or \
                       (not input_exec_pin and isinstance(node, (K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction, K2Node_InputAction, K2Node_InputAxisEvent, K2Node_InputKey, K2Node_InputTouch, K2Node_InputAxisKeyEvent, K2Node_InputDebugKey, K2Node_FunctionEntry))):
                           unconnected_executable_nodes.append(node)

        if unconnected_executable_nodes:
            output_lines.append("## Unconnected Executable Blocks")
            output_lines.append("*(Found executable nodes/sequences not reached by main entry points)*")
            output_lines.append("")
            for node in unconnected_executable_nodes:
                node_desc_str = self.node_formatter._get_formatter_func(node)(node, set())
                output_lines.append(f"- {node_desc_str}")
            output_lines.append("\n---\n")

        final_output_string = '\n'.join(output_lines)
        return final_output_string

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
                    variables[var_name] = {'type': node.variable_type or '?', 'values': []}
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