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
                    K2Node_VariableSet, K2Node_CallFunction, K2Node_InputAxisKeyEvent)

if TYPE_CHECKING:
    from ..parser import BlueprintParser

ENABLE_PATH_TRACER_DEBUG = False # Set to True for verbose tracing output

class PathTracer:
    # --- Updated Prefixes for Tree Structure ---
    exec_prefix = "→ "
    line_cont = "│   "  # Prefix for continuing lines under an ongoing branch
    branch_join = "┣━━ " # Prefix for a branch that is NOT the last one
    branch_last = "┗━━ " # Prefix for the LAST branch at a level
    indent_space = "    " # Indentation for levels without a continuing line needed
    # -----------------------------------------

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

    # --- Updated trace_path signature and logic ---
    def trace_path(self,
                   start_node: Optional[Node],
                   processed_guids_in_path: Set[str],
                   processed_globally: Set[str],
                   indent_prefix: str = "", # This now holds the full prefix string like "│   ┣━━ "
                   is_last_segment: bool = True # Is this the last segment at its current level?
                   ) -> List[str]:
        """Recursively formats the execution path into Markdown lines using tree characters."""
        lines = []
        current_node: Optional[Node] = start_node
        max_depth = 70
        depth = 0
        is_first_node_in_call = True

        if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}TRACE PATH START: Node={self._get_node_ref_name(current_node)}, Indent='{indent_prefix}', Last={is_last_segment}", file=sys.stderr)

        current_comment_guid: Optional[str] = None

        while current_node and depth < max_depth:
            depth += 1
            current_guid = current_node.guid

            # --- Global Redundancy Check ---
            if current_guid in processed_globally and not is_first_node_in_call:
                ref_name = self._get_node_ref_name(current_node)
                lines.append(f"{indent_prefix}{self.exec_prefix}[Path continues in previously traced section: {ref_name}]")
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Node {current_guid} globally processed.", file=sys.stderr)
                return lines

            # --- Loop Detection (Path Specific) ---
            if current_guid in processed_guids_in_path:
                loop_node_name_str = self._get_node_ref_name(current_node)
                lines.append(f"{indent_prefix}{self.exec_prefix}[Execution loop back to: {loop_node_name_str}]")
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Node {current_guid} loop in path.", file=sys.stderr)
                return lines

            processed_guids_in_path.add(current_guid)

            # --- Node Skipping Logic (Comments, Knots, Pure Nodes) ---
            if isinstance(current_node, EdGraphNode_Comment):
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Skip: Comment node {current_guid}.", file=sys.stderr)
                current_node = None # Should not happen if entry point is chosen correctly
                continue

            if isinstance(current_node, K2Node_Knot):
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Skip: Knot node {current_guid}. Following link...", file=sys.stderr)
                processed_globally.add(current_guid)
                current_node = self._find_next_executable_node(current_node, lines, indent_prefix)
                is_first_node_in_call = False
                continue

            if current_node.is_pure():
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Skip Visually: Pure node {self._get_node_ref_name(current_node)}.", file=sys.stderr)
                processed_globally.add(current_guid)
                current_node = self._find_next_executable_node(current_node, lines, indent_prefix)
                is_first_node_in_call = False
                continue

            # --- Handle Comments ---
            node_comment_assoc = self.comment_handler.get_comment_for_node(current_guid)
            if node_comment_assoc != current_comment_guid:
                # Exiting previous comment block or entering a new one
                current_comment_guid = node_comment_assoc
                if current_comment_guid:
                    comment_node = self.comment_handler.comments.get(current_comment_guid)
                    if comment_node and comment_node.comment_text:
                        # Format comment using brackets
                        comment_text_clean = comment_node.comment_text.strip().replace('\n', ' ').replace('\r', '')
                        lines.append(f"{indent_prefix}[{comment_text_clean}]")
            # ---------------------

            # --- Format the Current EXECUTABLE Node ---
            if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  Format Node: {self._get_node_ref_name(current_node)}", file=sys.stderr)
            node_desc, primary_exec_output = self.node_formatter.format_node(current_node, indent_prefix, processed_guids_in_path.copy())

            # --- Add Node Description ---
            if node_desc is not None:
                lines.append(f"{indent_prefix}{self.exec_prefix}{node_desc}")
                processed_globally.add(current_guid)
            else:
                lines.append(f"{indent_prefix}{self.exec_prefix}[Skipped Node: {self._get_node_ref_name(current_node)}]")
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  WARNING: Node formatter skipped non-pure node {current_guid}", file=sys.stderr)
                processed_globally.add(current_guid)
                primary_exec_output = current_node.get_execution_output_pin()

            if isinstance(current_node, K2Node_FunctionResult):
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Return node {current_guid}.", file=sys.stderr)
                current_node = None
                break

            # --- Branching Logic ---
            branching_node = current_node
            handled_as_branch = False
            # Get all *visible* execution output pins to determine branches
            exec_output_pins = [p for p in branching_node.get_output_pins(category="exec", include_hidden=False) if p.linked_pins]

            # Determine if this node requires branching based on its type and pin count
            is_branching_type = isinstance(branching_node, (
                K2Node_IfThenElse, K2Node_ExecutionSequence, K2Node_Switch,
                K2Node_ForEachLoop, K2Node_FlipFlop, K2Node_DynamicCast, K2Node_Timeline,
                K2Node_InputAction, K2Node_InputKey, K2Node_InputTouch, K2Node_InputDebugKey, K2Node_InputAxisKeyEvent, # Added InputAxisKeyEvent
                K2Node_EnhancedInputAction, K2Node_LatentAction
            )) or (isinstance(branching_node, K2Node_MacroInstance) and getattr(branching_node, 'macro_type', None) in ("IsValid", "Gate", "ForEachLoop", "ForEachLoopWithBreak", "ForLoop", "ForLoopWithBreak", "WhileLoop", "DoN", "DoOnce", "MultiGate"))

            # Check if it *actually* branches (more than one linked output exec pin)
            # Or if it's a type that *always* implies branching structure (like If, Sequence, Switch, Loop)
            needs_branch_handling = is_branching_type or len(exec_output_pins) > 1

            if needs_branch_handling:
                handled_as_branch = True
                # Determine the correct prefix for child branches based on whether
                # the *current* path segment is the last one at its level.
                child_base_indent = indent_prefix.replace(self.branch_join, self.line_cont).replace(self.branch_last, self.indent_space)

                # Define branches to trace based on node type
                branches_to_trace: List[Tuple[Optional[Pin], str]] = []

                if isinstance(branching_node, K2Node_IfThenElse):
                    branches_to_trace = [(branching_node.get_true_pin(), "True:"), (branching_node.get_false_pin(), "False:")]
                elif isinstance(branching_node, K2Node_ExecutionSequence):
                    branches_to_trace = [(pin, f"Then {i}:") for i, pin in enumerate(branching_node.get_execution_output_pins())]
                elif isinstance(branching_node, K2Node_Switch):
                    case_pins = branching_node.get_case_pins()
                    default_pin = branching_node.get_default_pin()
                    for pin in case_pins:
                        pin_label = pin.friendly_name if isinstance(branching_node, K2Node_SwitchEnum) and pin.friendly_name else pin.name
                        if pin_label and '.' in pin_label: pin_label = pin_label.split('.')[-1]
                        branches_to_trace.append((pin, f"Case `{pin_label}`:"))
                    if default_pin: branches_to_trace.append((default_pin, "Default:"))
                elif isinstance(branching_node, K2Node_ForEachLoop):
                     branches_to_trace = [(branching_node.get_loop_body_pin(), "Loop Body:"), (branching_node.get_completed_pin(), "Completed:")]
                elif isinstance(branching_node, (K2Node_FlipFlop, K2Node_MacroInstance)) and getattr(branching_node, 'macro_type', None) == "FlipFlop":
                     branches_to_trace = [(branching_node.get_pin(pin_name="A"), "A:"), (branching_node.get_pin(pin_name="B"), "B:")]
                elif isinstance(branching_node, K2Node_DynamicCast):
                    branches_to_trace = [(branching_node.get_success_pin(), "Success:"), (branching_node.get_failed_pin(), "Cast Failed:")]
                elif isinstance(branching_node, K2Node_Timeline):
                    branches_to_trace = [(branching_node.get_update_pin(), "Update:"), (branching_node.get_finished_pin(), "Finished:")]
                elif isinstance(branching_node, (K2Node_InputAction, K2Node_InputKey, K2Node_InputTouch, K2Node_InputDebugKey, K2Node_InputAxisKeyEvent)):
                    pressed_pin = branching_node.get_pressed_pin()
                    released_pin = branching_node.get_released_pin()
                    if pressed_pin or released_pin:
                        branches_to_trace = [(pressed_pin, "Pressed:"), (released_pin, "Released:")]
                    else: # Fallback for other Input types if necessary
                         branches_to_trace = [(pin, f"{pin.name}:") for pin in exec_output_pins]
                elif isinstance(branching_node, K2Node_EnhancedInputAction):
                     branches_to_trace = [(pin, f"{pin.name}:") for pin in branching_node.get_execution_output_pins()]
                elif isinstance(branching_node, K2Node_MacroInstance) and getattr(branching_node, 'macro_type', None) in ("IsValid", "Gate", "ForEachLoop", "ForEachLoopWithBreak", "ForLoop", "ForLoopWithBreak", "WhileLoop", "DoN", "DoOnce", "MultiGate"):
                    macro_type = branching_node.macro_type
                    if macro_type == "IsValid": branches_to_trace = [(branching_node.get_pin("Is Valid"), "Is Valid:"), (branching_node.get_pin("Is Not Valid"), "Is Not Valid:")]
                    elif macro_type in ("ForEachLoop", "ForEachLoopWithBreak", "ForLoop", "ForLoopWithBreak", "WhileLoop"): branches_to_trace = [(branching_node.get_pin("Loop Body"), "Loop Body:"), (branching_node.get_pin("Completed"), "Completed:")]
                    elif macro_type == "DoN": branches_to_trace = [(branching_node.get_pin("Exit"), "Exit:")]
                    elif macro_type == "DoOnce": branches_to_trace = [(branching_node.get_pin("Completed"), "Completed:")]
                    elif macro_type == "MultiGate": branches_to_trace = [(pin, f"{pin.name}:") for pin in branching_node.get_output_pins(category="exec", name_regex=r'Out \d*')]
                    elif macro_type == "Gate": branches_to_trace = [(branching_node.get_pin("Exit"), "Exit:")]
                elif isinstance(branching_node, K2Node_LatentAction): # Generic Latent Action
                     branches_to_trace = [(pin, f"{pin.name}:") for pin in exec_output_pins]
                else: # Default branching for unrecognized multi-output nodes
                    branches_to_trace = [(pin, f"{pin.name}:") for pin in exec_output_pins]

                # Filter out unlinked branches before tracing
                valid_branches = [(pin, label) for pin, label in branches_to_trace if pin and pin.linked_pins]

                # Trace valid branches
                num_valid_branches = len(valid_branches)
                for i, (pin, label) in enumerate(valid_branches):
                    is_last_branch = (i == num_valid_branches - 1)
                    branch_prefix = self.branch_last if is_last_branch else self.branch_join
                    full_branch_prefix = child_base_indent + branch_prefix
                    lines.append(f"{full_branch_prefix}{label}") # Add the branch label line

                    # Determine the prefix for nodes *inside* this branch
                    # If this is the last branch, the continuation uses spaces, otherwise lines
                    next_indent_prefix = child_base_indent + (self.indent_space if is_last_branch else self.line_cont)

                    target_pin = pin.linked_pins[0]
                    target_node = self.parser.get_node_by_guid(target_pin.node_guid)
                    if target_node:
                        branch_lines = self.trace_path(target_node, processed_guids_in_path.copy(), processed_globally, next_indent_prefix, is_last_branch)
                        lines.extend(branch_lines)
                    else:
                         lines.append(f"{next_indent_prefix}{self.exec_prefix}[Branch '{label}' leads to missing node: {target_pin.node_guid[:8]}]")

            if handled_as_branch:
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Branching handled for node {current_guid}.", file=sys.stderr)
                current_node = None # Stop linear traversal after handling branches
                break

            # --- Standard Linear Continuation ---
            # Determine the correct prefix for the *next* node in the linear path
            next_linear_indent = indent_prefix.replace(self.branch_join, self.line_cont).replace(self.branch_last, self.indent_space)
            next_node_in_path = self._find_next_executable_node(current_node, lines, next_linear_indent, primary_exec_output)
            current_node = next_node_in_path
            indent_prefix = next_linear_indent # Update indent_prefix for the next iteration
            is_first_node_in_call = False


        if depth >= max_depth:
            lines.append(f"{indent_prefix}{self.exec_prefix}[Trace depth limit reached ({max_depth})]")
            if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Max depth reached.", file=sys.stderr)

        if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}TRACE PATH END: Node={self._get_node_ref_name(start_node)}. Returning {len(lines)} lines.", file=sys.stderr)
        return lines

    # --- Modified _find_next_executable_node slightly to pass indent_prefix ---
    def _find_next_executable_node(self, current_node: Node, lines: List[str], indent_prefix: str, primary_exec_pin: Optional[Pin] = None) -> Optional[Node]:
        """
        Finds the next non-pure, non-comment, non-knot node following the execution or data path.
        Handles the end-of-path messages.
        """
        search_depth = 0
        max_search_depth = 15
        temp_node = current_node
        visited_pure_or_knot = {current_node.guid}

        while search_depth < max_search_depth:
            search_depth += 1
            next_pin: Optional[Pin] = None

            if temp_node.is_pure() or isinstance(temp_node, K2Node_Knot):
                output_pins = temp_node.get_output_pins()
                if isinstance(temp_node, K2Node_Knot):
                    next_pin = temp_node.get_passthrough_output_pin()
                elif output_pins:
                    next_pin = temp_node.get_pin("ReturnValue") or \
                                next((p for p in output_pins if not p.is_hidden()), None) or \
                                output_pins[0]
                else:
                    if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Pure/Knot node {self._get_node_ref_name(temp_node)} has no output pins.", file=sys.stderr)
                    return None
            else:
                next_pin = primary_exec_pin if primary_exec_pin else temp_node.get_execution_output_pin()

            if not next_pin:
                lines.append(f"{indent_prefix}{self.exec_prefix}[Path ends: No relevant output pin]")
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Node {self._get_node_ref_name(temp_node)} has no output pin to follow.", file=sys.stderr)
                return None

            if not next_pin.linked_pins:
                lines.append(f"{indent_prefix}{self.exec_prefix}[Path ends: Pin '{next_pin.name}' unlinked]")
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Pin {next_pin.name} on {self._get_node_ref_name(temp_node)} is unlinked.", file=sys.stderr)
                return None

            found_executable_target = None
            next_temp_node_candidate = None
            for target_pin in next_pin.linked_pins:
                candidate_node = self.parser.get_node_by_guid(target_pin.node_guid)

                if not candidate_node:
                    lines.append(f"{indent_prefix}{self.exec_prefix}[Path ends: Linked node missing {target_pin.node_guid[:8]}]")
                    if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Linked node {target_pin.node_guid} missing.", file=sys.stderr)
                    continue

                if candidate_node.guid in visited_pure_or_knot:
                    if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Skip Link: Node {self._get_node_ref_name(candidate_node)} already visited in pure/knot search.", file=sys.stderr)
                    continue

                if not candidate_node.is_pure() and not isinstance(candidate_node, (K2Node_Knot, EdGraphNode_Comment)):
                    found_executable_target = candidate_node
                    break # Found executable target

                elif not isinstance(candidate_node, EdGraphNode_Comment):
                    # Store the first pure/knot candidate to continue searching from, but keep checking other links first
                    if next_temp_node_candidate is None:
                         if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Candidate Pure/Knot: Following link to {self._get_node_ref_name(candidate_node)}.", file=sys.stderr)
                         next_temp_node_candidate = candidate_node
                         visited_pure_or_knot.add(next_temp_node_candidate.guid)
                else:
                    if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Skip Link: Target is comment node {self._get_node_ref_name(candidate_node)}.", file=sys.stderr)
                    continue

            # After checking all links for the current pin:
            if found_executable_target:
                return found_executable_target

            # If no executable node found, but we found a pure/knot candidate, continue search from it
            if next_temp_node_candidate:
                temp_node = next_temp_node_candidate
                continue # Continue while loop

            # If we checked all links and found neither executable nor pure/knot candidate
            lines.append(f"{indent_prefix}{self.exec_prefix}[Path ends: Connection leads only to comments or unlinked nodes]")
            if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Could not find next executable node after {self._get_node_ref_name(current_node)}.", file=sys.stderr)
            return None

        # Max search depth reached
        lines.append(f"{indent_prefix}{self.exec_prefix}[Trace depth limit reached ({max_search_depth})]")
        if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Max search depth reached.", file=sys.stderr)
        return None

    # _trace_branch is removed as its logic is integrated into trace_path
    # def _trace_branch(...): # REMOVED