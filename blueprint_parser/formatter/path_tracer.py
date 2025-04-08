# blueprint_parser/formatter/path_tracer.py

# blueprint_parser/formatter/path_tracer.py

from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING
import sys
# --- Use relative imports ---
from .node_formatter import NodeFormatter
from .comment_handler import CommentHandler
# --- Use relative imports ---
from ..nodes import (Node, Pin, K2Node_Knot, EdGraphNode_Comment, K2Node_IfThenElse, K2Node_ExecutionSequence, \
                    K2Node_FlipFlop, K2Node_DynamicCast, K2Node_MacroInstance, K2Node_Switch, K2Node_SwitchEnum, \
                    K2Node_ForEachLoop, K2Node_Timeline, K2Node_InputAction, K2Node_InputKey, K2Node_InputTouch, \
                    K2Node_InputDebugKey, K2Node_EnhancedInputAction, K2Node_LatentAction, K2Node_PlayMontage, K2Node_FunctionResult,
                    K2Node_VariableSet, K2Node_CallFunction, K2Node_InputAxisKeyEvent) # Added InputAxisKeyEvent

if TYPE_CHECKING:
    from ..parser import BlueprintParser

ENABLE_PATH_TRACER_DEBUG = False # Set to True for verbose tracing output

class PathTracer:
    exec_prefix = "→ " # Use an arrow for execution flow
    branch_indent_increment = "    " # 4 spaces for indentation

    def __init__(self, parser: 'BlueprintParser', node_formatter: 'NodeFormatter', comment_handler: 'CommentHandler'):
        self.parser = parser
        self.node_formatter = node_formatter
        self.comment_handler = comment_handler
        if ENABLE_PATH_TRACER_DEBUG: print(f"DEBUG (PathTracer): Initialized.", file=sys.stderr)

    def _get_node_ref_name(self, node: Optional[Node]) -> str:
        """Helper method to get a reference name for a node."""
        if not node: return "`Unknown Node`"
        name_part = node.name or node.node_type
        return f"`{name_part}` ({node.guid[:8]})"

    # --- Updated trace_path to skip pure nodes visually ---
    def trace_path(self, start_node: Optional[Node], processed_guids_in_path: Set[str], processed_globally: Set[str], indent: str = "", current_branch_label: Optional[str] = None) -> List[str]:
        """Recursively formats the execution path into Markdown lines, skipping pure nodes visually."""
        lines = []
        current_node: Optional[Node] = start_node
        max_depth = 70 # Increased limit slightly
        depth = 0
        is_first_node_in_call = True

        if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}TRACE PATH START: Node={self._get_node_ref_name(current_node)}, Branch='{current_branch_label}', Indent='{len(indent)}'", file=sys.stderr)

        while current_node and depth < max_depth:
            depth += 1
            current_guid = current_node.guid

            # --- Global Redundancy Check ---
            if current_guid in processed_globally and not is_first_node_in_call:
                ref_name = self._get_node_ref_name(current_node)
                lines.append(f"{indent}{self.exec_prefix}[Path continues in previously traced section: {ref_name}]")
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Stop: Node {current_guid} globally processed.", file=sys.stderr)
                return lines

            # --- Loop Detection (Path Specific) ---
            if current_guid in processed_guids_in_path:
                loop_node_name_str = self._get_node_ref_name(current_node)
                lines.append(f"{indent}{self.exec_prefix}[Execution loop back to: {loop_node_name_str}]")
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Stop: Node {current_guid} loop in path.", file=sys.stderr)
                return lines

            processed_guids_in_path.add(current_guid)

            # --- Node Skipping Logic (Comments, Knots, Pure Nodes) ---
            if isinstance(current_node, EdGraphNode_Comment):
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Skip: Comment node {current_guid}.", file=sys.stderr)
                current_node = None
                continue

            if isinstance(current_node, K2Node_Knot):
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Skip: Knot node {current_guid}. Following link...", file=sys.stderr)
                processed_globally.add(current_guid)
                # Find next non-knot node (helper function)
                current_node = self._find_next_executable_node(current_node, lines, indent)
                is_first_node_in_call = False
                continue

            # ---- NEW: Skip Pure Nodes Visually ----
            if current_node.is_pure():
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Skip Visually: Pure node {self._get_node_ref_name(current_node)}.", file=sys.stderr)
                processed_globally.add(current_guid) # Mark as processed even if skipped visually
                # Find the next *executable* node by tracing data flow briefly
                current_node = self._find_next_executable_node(current_node, lines, indent)
                is_first_node_in_call = False
                continue
            # -------------------------------------


            # --- Format the Current EXECUTABLE Node ---
            if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  Format Node: {self._get_node_ref_name(current_node)}", file=sys.stderr)
            node_desc, primary_exec_output = self.node_formatter.format_node(current_node, indent, processed_guids_in_path.copy())

            # --- Add Comment (if any) ---
            node_comment_text = self.comment_handler.get_comment(current_guid)
            if node_comment_text:
                comment_lines = node_comment_text.strip().split('\n')
                for comment_line in comment_lines:
                    lines.append(f"{indent}# {comment_line}")

            # --- Add Node Description ---
            if node_desc is not None:
                lines.append(f"{indent}{self.exec_prefix}{node_desc}")
                processed_globally.add(current_guid)
            else:
                # This case should be rarer now with the pure node check above
                lines.append(f"{indent}{self.exec_prefix}[Skipped Node: {self._get_node_ref_name(current_node)}]")
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  WARNING: Node formatter skipped non-pure node {current_guid}", file=sys.stderr)
                processed_globally.add(current_guid)
                primary_exec_output = current_node.get_execution_output_pin()

            if isinstance(current_node, K2Node_FunctionResult):
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Stop: Return node {current_guid}.", file=sys.stderr)
                current_node = None
                break

            # --- Branching Logic ---
            branching_node = current_node
            branch_content_indent = indent + self.branch_indent_increment
            handled_as_branch = False
            exec_output_pins = [p for p in branching_node.get_output_pins(category="exec", include_hidden=False)]

            # (Branching logic remains the same as before...)
            # Specific branching node types
            if isinstance(branching_node, K2Node_IfThenElse):
                self._trace_branch(lines, branching_node.get_true_pin(), "True", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                self._trace_branch(lines, branching_node.get_false_pin(), "False", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                handled_as_branch = True
            elif isinstance(branching_node, K2Node_ExecutionSequence):
                for i, pin in enumerate(branching_node.get_execution_output_pins()): # Use specific getter
                    self._trace_branch(lines, pin, f"Then {i}", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                handled_as_branch = True
            elif isinstance(branching_node, K2Node_Switch): # Handles Enum, Name, String, Int etc.
                case_pins = branching_node.get_case_pins()
                default_pin = branching_node.get_default_pin()
                for pin in case_pins:
                    # Use friendly name for Enums if available, otherwise raw pin name
                    pin_label = pin.friendly_name if isinstance(branching_node, K2Node_SwitchEnum) and pin.friendly_name else pin.name
                    if pin_label and '.' in pin_label: pin_label = pin_label.split('.')[-1] # Clean up enum name
                    case_label = f"Case `{pin_label}`" if pin_label else f"Case_{pin.id[:4]}"
                    self._trace_branch(lines, pin, case_label, branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                if default_pin:
                    self._trace_branch(lines, default_pin, "Default", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                handled_as_branch = True
            elif isinstance(branching_node, K2Node_ForEachLoop):
                self._trace_branch(lines, branching_node.get_loop_body_pin(), "Loop Body", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                self._trace_branch(lines, branching_node.get_completed_pin(), "Completed", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                handled_as_branch = True
            elif isinstance(branching_node, (K2Node_FlipFlop, K2Node_MacroInstance)) and getattr(branching_node, 'macro_type', None) == "FlipFlop":
                self._trace_branch(lines, branching_node.get_pin(pin_name="A"), "A", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                self._trace_branch(lines, branching_node.get_pin(pin_name="B"), "B", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                handled_as_branch = True
            elif isinstance(branching_node, K2Node_DynamicCast):
                self._trace_branch(lines, branching_node.get_success_pin(), "Success", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                self._trace_branch(lines, branching_node.get_failed_pin(), "Cast Failed", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                handled_as_branch = True
            elif isinstance(branching_node, K2Node_Timeline):
                self._trace_branch(lines, branching_node.get_update_pin(), "Update", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                self._trace_branch(lines, branching_node.get_finished_pin(), "Finished", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                handled_as_branch = True
            elif isinstance(branching_node, (K2Node_InputAction, K2Node_InputKey, K2Node_InputTouch, K2Node_InputDebugKey, K2Node_InputAxisKeyEvent)): # Added InputAxisKeyEvent
                # Check specifically for Pressed/Released type outputs
                pressed_pin = branching_node.get_pressed_pin()
                released_pin = branching_node.get_released_pin()
                if pressed_pin or released_pin:
                    self._trace_branch(lines, pressed_pin, "Pressed", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                    self._trace_branch(lines, released_pin, "Released", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                    handled_as_branch = True
                # If not Pressed/Released pattern, fall through to generic branching
            elif isinstance(branching_node, K2Node_EnhancedInputAction):
                # Trace all execution outputs by name
                for pin in branching_node.get_execution_output_pins(): # Use specific getter
                    label = pin.name or f"Exec_{pin.id[:4]}"
                    self._trace_branch(lines, pin, label, branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                handled_as_branch = True
            elif isinstance(branching_node, K2Node_MacroInstance) and getattr(branching_node, 'macro_type', None) in ("IsValid", "Gate", "ForEachLoop", "ForEachLoopWithBreak", "ForLoop", "ForLoopWithBreak", "WhileLoop", "DoN", "DoOnce", "MultiGate"):
                # Handle known branching macros explicitly
                macro_type = branching_node.macro_type
                if macro_type == "IsValid":
                    self._trace_branch(lines, branching_node.get_pin("Is Valid"), "Is Valid", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                    self._trace_branch(lines, branching_node.get_pin("Is Not Valid"), "Is Not Valid", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                elif macro_type in ("ForEachLoop", "ForEachLoopWithBreak"):
                    self._trace_branch(lines, branching_node.get_pin("Loop Body"), "Loop Body", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                    self._trace_branch(lines, branching_node.get_pin("Completed"), "Completed", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                elif macro_type in ("ForLoop", "ForLoopWithBreak"):
                    self._trace_branch(lines, branching_node.get_pin("Loop Body"), "Loop Body", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                    self._trace_branch(lines, branching_node.get_pin("Completed"), "Completed", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                elif macro_type == "WhileLoop":
                    self._trace_branch(lines, branching_node.get_pin("Loop Body"), "Loop Body", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                    self._trace_branch(lines, branching_node.get_pin("Completed"), "Completed", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                elif macro_type == "DoN":
                    self._trace_branch(lines, branching_node.get_pin("Exit"), "Exit", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                elif macro_type == "DoOnce":
                    self._trace_branch(lines, branching_node.get_pin("Completed"), "Completed", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                elif macro_type == "MultiGate":
                    for pin in branching_node.get_output_pins(category="exec", name_regex=r'Out \d*'):
                         self._trace_branch(lines, pin, pin.name, branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                elif macro_type == "Gate":
                    self._trace_branch(lines, branching_node.get_pin("Exit"), "Exit", branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                handled_as_branch = True
            elif isinstance(branching_node, K2Node_LatentAction) and len(exec_output_pins) > 1:
                # Handle generic latent actions with multiple outputs (e.g., Completed, OnNotify, etc.)
                for pin in exec_output_pins:
                    label = pin.name or f"Exec_{pin.id[:4]}"
                    self._trace_branch(lines, pin, label, branch_content_indent, processed_guids_in_path.copy(), processed_globally)
                handled_as_branch = True


            if handled_as_branch:
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Stop: Branching handled for node {current_guid}.", file=sys.stderr)
                current_node = None
                break

            # --- Standard Linear Continuation ---
            next_node_in_path = self._find_next_executable_node(current_node, lines, indent, primary_exec_output)
            current_node = next_node_in_path
            is_first_node_in_call = False

        if depth >= max_depth:
            lines.append(f"{indent}{self.exec_prefix}[Trace depth limit reached ({max_depth})]")
            if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Stop: Max depth reached.", file=sys.stderr)

        if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}TRACE PATH END: Node={self._get_node_ref_name(start_node)}, Branch='{current_branch_label}'. Returning {len(lines)} lines.", file=sys.stderr)
        return lines


    def _find_next_executable_node(self, current_node: Node, lines: List[str], indent: str, primary_exec_pin: Optional[Pin] = None) -> Optional[Node]:
        """
        Finds the next non-pure, non-comment, non-knot node following the execution or data path.
        Handles the end-of-path messages.
        """
        search_depth = 0
        max_search_depth = 15 # Limit search for next executable node
        temp_node = current_node
        visited_pure_or_knot = {current_node.guid}

        while search_depth < max_search_depth:
            search_depth += 1
            next_pin: Optional[Pin] = None

            if temp_node.is_pure() or isinstance(temp_node, K2Node_Knot):
                # If pure or knot, find the primary *data* output pin
                output_pins = temp_node.get_output_pins() # Get all output pins
                if isinstance(temp_node, K2Node_Knot):
                    next_pin = temp_node.get_passthrough_output_pin()
                elif output_pins:
                    # Prefer 'ReturnValue' or the first non-hidden pin
                    next_pin = temp_node.get_pin("ReturnValue") or \
                                next((p for p in output_pins if not p.is_hidden()), None) or \
                                output_pins[0]
                else:
                    # Pure/Knot node with no output? End of this data path segment.
                    if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Stop: Pure/Knot node {self._get_node_ref_name(temp_node)} has no output pins.", file=sys.stderr)
                    return None # Cannot continue
            else:
                # If executable, use the primary exec output pin provided (or find it)
                next_pin = primary_exec_pin if primary_exec_pin else temp_node.get_execution_output_pin()

            if not next_pin:
                # No relevant output pin found on the current node
                lines.append(f"{indent}{self.exec_prefix}[Path ends: No relevant output pin]")
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Stop: Node {self._get_node_ref_name(temp_node)} has no output pin to follow.", file=sys.stderr)
                return None

            if not next_pin.linked_pins:
                # Output pin is not linked
                lines.append(f"{indent}{self.exec_prefix}[Path ends: Pin '{next_pin.name}' unlinked]")
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Stop: Pin {next_pin.name} on {self._get_node_ref_name(temp_node)} is unlinked.", file=sys.stderr)
                return None

            # Follow the link(s) - Check all linked pins
            # In execution paths, we usually only care about the first link,
            # but for data paths from pure nodes, multiple links might exist.
            # We need to find the *first* linked node that is executable.
            found_executable_target = None
            for target_pin in next_pin.linked_pins:
                candidate_node = self.parser.get_node_by_guid(target_pin.node_guid)

                if not candidate_node:
                    lines.append(f"{indent}{self.exec_prefix}[Path ends: Linked node missing {target_pin.node_guid[:8]}]")
                    if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Stop: Linked node {target_pin.node_guid} missing.", file=sys.stderr)
                    continue # Check next link if any

                if candidate_node.guid in visited_pure_or_knot:
                    if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Skip Link: Node {self._get_node_ref_name(candidate_node)} already visited in pure/knot search.", file=sys.stderr)
                    continue # Avoid loops within this search

                if not candidate_node.is_pure() and not isinstance(candidate_node, (K2Node_Knot, EdGraphNode_Comment)):
                     # Found the next executable node
                    found_executable_target = candidate_node
                    break # Stop searching links for this pin

                # If the linked node is pure/knot/comment, continue the search from it
                elif not isinstance(candidate_node, EdGraphNode_Comment): # Don't traverse into comments
                    if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Traversing Pure/Knot: Following link to {self._get_node_ref_name(candidate_node)}.", file=sys.stderr)
                    temp_node = candidate_node
                    visited_pure_or_knot.add(temp_node.guid)
                    # Break the inner link loop and continue the outer while loop from this new pure/knot node
                    break
                else: # Linked to a comment
                    if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Skip Link: Target is comment node {self._get_node_ref_name(candidate_node)}.", file=sys.stderr)
                    continue # Check other links from the *original* pin

            # After checking all links for the current pin:
            if found_executable_target:
                return found_executable_target # Return the executable node found

            # If we finished checking links for the current 'next_pin' and didn't find an executable node,
            # but we *did* jump to a new pure/knot node (`temp_node` was updated), continue the outer loop.
            if temp_node.guid != current_node.guid and (temp_node.is_pure() or isinstance(temp_node, K2Node_Knot)):
                continue # Continue while loop from the new pure/knot node

            # If we checked all links and didn't find an executable node and didn't jump to a new pure/knot node, the path ends here.
            # This might happen if a data pin only links to other pure nodes that eventually dead-end.
            lines.append(f"{indent}{self.exec_prefix}[Path ends: Connection leads only to pure/unlinked nodes]")
            if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Stop: Could not find next executable node after {self._get_node_ref_name(current_node)}.", file=sys.stderr)
            return None

        # Max search depth reached
        lines.append(f"{indent}{self.exec_prefix}[Path ends: Search limit reached while finding next executable node]")
        if ENABLE_PATH_TRACER_DEBUG: print(f"{indent}  -> Stop: Max search depth reached.", file=sys.stderr)
        return None


    # --- _trace_branch remains the same ---
    def _trace_branch(self, lines: List[str], pin: Optional[Pin], branch_name: str, branch_indent: str, processed_in_path: Set[str], processed_globally: Set[str]):
        """Helper method to trace a specific branch from a pin."""
        if not pin or not pin.linked_pins:
            if ENABLE_PATH_TRACER_DEBUG: print(f"{branch_indent}Skip Branch '{branch_name}': Pin invalid or unlinked.", file=sys.stderr)
            return

        lines.append(f"{branch_indent}**{branch_name}:**")

        target_pin = pin.linked_pins[0]
        target_node = self.parser.get_node_by_guid(target_pin.node_guid)

        if not target_node:
            lines.append(f"{branch_indent}{self.exec_prefix}[Branch '{branch_name}' leads to missing node: {target_pin.node_guid[:8]}]")
            if ENABLE_PATH_TRACER_DEBUG: print(f"{branch_indent}  -> Branch '{branch_name}' target node missing.", file=sys.stderr)
            return

        branch_lines = self.trace_path(target_node, processed_in_path, processed_globally, branch_indent, branch_name)
        lines.extend(branch_lines)