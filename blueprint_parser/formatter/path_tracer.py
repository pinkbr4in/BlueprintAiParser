# blueprint_parser/formatter/path_tracer.py

from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING
import sys
# --- Use relative imports ---
from .node_formatter import NodeFormatter
from .comment_handler import CommentHandler
# --- Import strip_html_tags from the correct location ---
from ..utils import strip_html_tags # Assuming strip_html_tags is in utils.py
# --- Use relative imports ---
from ..nodes import (Node, Pin, K2Node_Knot, EdGraphNode_Comment, K2Node_IfThenElse, K2Node_ExecutionSequence, \
                     K2Node_FlipFlop, K2Node_DynamicCast, K2Node_MacroInstance, K2Node_Switch, K2Node_SwitchEnum, \
                     K2Node_ForEachLoop, K2Node_Timeline, K2Node_InputAction, K2Node_InputKey, K2Node_InputTouch, \
                     K2Node_InputDebugKey, K2Node_EnhancedInputAction, K2Node_LatentAction, K2Node_PlayMontage, K2Node_FunctionResult,
                     K2Node_VariableSet, K2Node_CallFunction, K2Node_InputAxisKeyEvent) # Make sure all needed node types are imported

if TYPE_CHECKING:
    from ..parser import BlueprintParser

ENABLE_PATH_TRACER_DEBUG = False # Set to True for verbose tracing output

class PathTracer:
    # --- Updated Prefixes for Tree Structure ---
    exec_prefix = "→ " # Changed for clarity
    line_cont = "│   " # Prefix for continuing lines under an ongoing branch
    branch_join = "├── " # Prefix for a branch that is NOT the last one
    branch_last = "└── " # Prefix for the LAST branch at a level
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
                   indent_prefix: str = "", # This now holds the full prefix string like "│   ├── "
                   is_last_segment: bool = True # Is this the last segment at its current level?
                   ) -> List[str]:
        """Recursively formats the execution path into Markdown lines using tree characters."""
        lines = []
        current_node: Optional[Node] = start_node
        max_depth = 70 # Increased max depth slightly
        depth = 0
        is_first_node_in_call = True # Track if it's the very first node of this trace_path call

        if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}TRACE PATH START: Node={self._get_node_ref_name(current_node)}, Indent='{indent_prefix}', Last={is_last_segment}", file=sys.stderr)

        current_comment_guid: Optional[str] = None

        while current_node and depth < max_depth:
            depth += 1
            current_guid = current_node.guid

            # --- Global Redundancy Check ---
            # Check if processed globally *unless* it's the very first node being formatted in this specific trace_path call
            if current_guid in processed_globally and not is_first_node_in_call:
                # --- MODIFICATION START: Format target node description ---
                target_node = self.parser.get_node_by_guid(current_guid)
                target_desc_plain = self._get_node_ref_name(target_node) # Default fallback name
                if target_node:
                     # Format description without prefix, using a new visited set
                     # Use an empty set for visited_nodes as we just need the description, not recursive data tracing here.
                     target_desc_html, _ = self.node_formatter.format_node(target_node, "", set())
                     if target_desc_html:
                          target_desc_plain = strip_html_tags(target_desc_html)
                lines.append(f"{indent_prefix}{self.exec_prefix}[Path continues from previously traced node: {target_desc_plain}]")
                # --- MODIFICATION END ---
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Node {current_guid} globally processed.", file=sys.stderr)
                return lines

            # --- Loop Detection (Path Specific) ---
            if current_guid in processed_guids_in_path:
                loop_node_name_str = self._get_node_ref_name(current_node)
                lines.append(f"{indent_prefix}{self.exec_prefix}[Execution loop back to: {loop_node_name_str}]")
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Node {current_guid} loop in path.", file=sys.stderr)
                return lines

            processed_guids_in_path.add(current_guid) # Add to path-specific visited set

            # --- Node Skipping Logic (Comments, Knots, Pure Nodes) ---
            if isinstance(current_node, EdGraphNode_Comment):
                # Comments are handled separately based on association
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Skip Visually: Comment node {current_guid}.", file=sys.stderr)
                # Attempt to find the next node if a comment was somehow the entry
                processed_globally.add(current_guid) # Mark comment as processed globally
                # Note: _find_next_executable_node won't be called on a comment directly,
                # it should be skipped by the caller or during the search from the previous node.
                # If a comment IS the start_node, this path will simply end unless linked differently.
                current_node = None # Treat as end of path for now if it's the starting point
                is_first_node_in_call = False
                continue

            if isinstance(current_node, K2Node_Knot):
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Skip Visually: Knot node {current_guid}. Following link...", file=sys.stderr)
                processed_globally.add(current_guid) # Mark knot as processed globally
                # The 'indent_prefix' for the *search* doesn't change structure, but we pass it for debug prints
                current_node = self._find_next_executable_node(current_node, lines, indent_prefix)
                is_first_node_in_call = False # No longer the first node in this call sequence
                continue

            if current_node.is_pure():
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Skip Visually: Pure node {self._get_node_ref_name(current_node)}.", file=sys.stderr)
                processed_globally.add(current_guid) # Mark pure node as processed globally
                # Pure nodes don't have exec output pins to follow linearly.
                # Attempt to find the *next* node based on data links (handled by _find_next_executable_node logic)
                # We can't just follow exec pins. Let _find_next handle it if possible, otherwise path ends.
                # This path segment effectively ends here if _find_next returns None.
                current_node = self._find_next_executable_node(current_node, lines, indent_prefix)
                is_first_node_in_call = False # No longer the first node in this call sequence
                continue # Continue loop with the node found by _find_next (or None)

            # --- Mark Node as Globally Processed (Only Executable Nodes) ---
            # Do this *before* handling branches to prevent infinite loops if branches lead back immediately
            processed_globally.add(current_guid)

            # --- Handle Comments ---
            node_comment_assoc = self.comment_handler.get_comment_for_node(current_guid)
            if node_comment_assoc != current_comment_guid:
                current_comment_guid = node_comment_assoc
                if current_comment_guid:
                    comment_node = self.comment_handler.comments.get(current_comment_guid)
                    if comment_node and comment_node.comment_text:
                        comment_text_clean = comment_node.comment_text.strip().replace('\n', ' ').replace('\r', '')
                        # Use the current node's indent prefix for the comment line
                        lines.append(f"{indent_prefix}[{comment_text_clean}]")
            # ---------------------

            # --- Format the Current EXECUTABLE Node ---
            if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  Format Node: {self._get_node_ref_name(current_node)}", file=sys.stderr)
            # Pass a *copy* of the path-specific visited set for data tracing within this node's args
            node_desc, primary_exec_output = self.node_formatter.format_node(current_node, indent_prefix, processed_guids_in_path.copy())

            if node_desc is not None:
                # Apply the execution prefix only to the line with the node description itself
                lines.append(f"{indent_prefix}{self.exec_prefix}{node_desc}")
            else: # Should only happen if formatter explicitly returns None (e.g., Literal)
                # If formatter skipped it, we still need to find the next node
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  Node Formatter returned None for {current_guid}. Finding next executable.", file=sys.stderr)
                # Need to determine the correct indent for the *search* starting from this skipped node
                # Assume linear continuation for the search indent calculation
                next_linear_indent_for_search = indent_prefix + (self.indent_space if is_last_segment else self.line_cont)
                current_node = self._find_next_executable_node(current_node, lines, next_linear_indent_for_search)
                is_first_node_in_call = False
                continue # Skip branching logic for nodes formatted as None

            # --- Check for Return Node ---
            if isinstance(current_node, K2Node_FunctionResult):
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Return node {current_guid}.", file=sys.stderr)
                current_node = None # Stop this path
                break # Exit while loop

            # --- Branching Logic ---
            branching_node = current_node # Keep reference to the node causing potential branches
            handled_as_branch = False
            # Get all *visible* execution output pins that have links
            exec_output_pins = [p for p in branching_node.get_output_pins(category="exec", include_hidden=False) if p.linked_pins]

            # Determine if this node requires branching structure
            is_branching_type = isinstance(branching_node, (
                K2Node_IfThenElse, K2Node_ExecutionSequence, K2Node_Switch,
                K2Node_ForEachLoop, K2Node_FlipFlop, K2Node_DynamicCast, K2Node_Timeline,
                K2Node_InputAction, K2Node_InputKey, K2Node_InputTouch, K2Node_InputDebugKey, K2Node_InputAxisKeyEvent, # Added InputAxisKeyEvent
                K2Node_EnhancedInputAction, K2Node_LatentAction
            )) or (isinstance(branching_node, K2Node_MacroInstance) and getattr(branching_node, 'macro_type', None) in ("IsValid", "Gate", "ForEachLoop", "ForEachLoopWithBreak", "ForLoop", "ForLoopWithBreak", "WhileLoop", "DoN", "DoOnce", "MultiGate"))

            needs_branch_handling = is_branching_type or len(exec_output_pins) > 1

            if needs_branch_handling:
                handled_as_branch = True
                # Determine correct prefix for child branches based on whether the *current* segment is the last
                # Child base indent removes the current node's branch prefix (┣━━ or ┗━━)
                # and replaces it with appropriate continuation (│   ) or spacing (    ).
                child_base_indent = indent_prefix + (self.indent_space if is_last_segment else self.line_cont)

                # Define branches based on node type (using output pins directly is often better)
                branches_to_trace: List[Tuple[Optional[Pin], str]] = []

                # --- (Branch definition logic remains the same as in the 'new' code) ---
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
                    # Use specific pins if available, otherwise fall back to all exec outputs
                    if pressed_pin or released_pin:
                        branches_to_trace = [(pressed_pin, "Pressed:"), (released_pin, "Released:")]
                    else:
                         branches_to_trace = [(pin, f"{pin.name}:") for pin in exec_output_pins] # Use all linked exec pins
                elif isinstance(branching_node, K2Node_EnhancedInputAction):
                     # Use the helper that returns them in preferred order
                     branches_to_trace = [(pin, f"{pin.name}:") for pin in branching_node.get_execution_output_pins()]
                elif isinstance(branching_node, K2Node_MacroInstance) and getattr(branching_node, 'macro_type', None) in ("IsValid", "Gate", "ForEachLoop", "ForEachLoopWithBreak", "ForLoop", "ForLoopWithBreak", "WhileLoop", "DoN", "DoOnce", "MultiGate"):
                    macro_type = branching_node.macro_type
                    if macro_type == "IsValid": branches_to_trace = [(branching_node.get_pin("Is Valid"), "Is Valid:"), (branching_node.get_pin("Is Not Valid"), "Is Not Valid:")]
                    elif macro_type in ("ForEachLoop", "ForEachLoopWithBreak", "ForLoop", "ForLoopWithBreak", "WhileLoop"): branches_to_trace = [(branching_node.get_pin("Loop Body"), "Loop Body:"), (branching_node.get_pin("Completed"), "Completed:")]
                    elif macro_type == "DoN": branches_to_trace = [(branching_node.get_pin("Exit"), "Exit:")] # DoN only has Exit exec output usually
                    elif macro_type == "DoOnce": branches_to_trace = [(branching_node.get_pin("Completed"), "Completed:")]
                    elif macro_type == "MultiGate": branches_to_trace = [(pin, f"{pin.name}:") for pin in branching_node.get_output_pins(category="exec", name_regex=r'Out \d*')]
                    elif macro_type == "Gate": branches_to_trace = [(branching_node.get_pin("Exit"), "Exit:")]
                elif isinstance(branching_node, K2Node_LatentAction): # Generic Latent Action
                     # Default to using all linked exec outputs
                     branches_to_trace = [(pin, f"{pin.name}:") for pin in exec_output_pins]
                else: # Default branching for unrecognized multi-output nodes
                    branches_to_trace = [(pin, f"{pin.name}:") for pin in exec_output_pins]
                # --- (End of Branch definition logic) ---

                # Filter out unlinked branches before tracing
                valid_branches = [(pin, label) for pin, label in branches_to_trace if pin and pin.linked_pins]

                # Trace valid branches
                num_valid_branches = len(valid_branches)
                for i, (pin, label) in enumerate(valid_branches):
                    is_last_branch = (i == num_valid_branches - 1)
                    branch_prefix_char = self.branch_last if is_last_branch else self.branch_join
                    # Combine the base indent (which has lines/spaces) with the branch char
                    full_branch_prefix = child_base_indent + branch_prefix_char
                    lines.append(f"{full_branch_prefix}{label}") # Add the branch label line

                    # Determine the prefix for nodes *inside* this branch
                    # If this is the last branch, the continuation uses spaces, otherwise lines
                    next_indent_prefix_branch = child_base_indent + (self.indent_space if is_last_branch else self.line_cont)

                    # Each branch starts a new trace segment. The 'is_last_segment' argument passed to the recursive call
                    # determines if *that branch's* content should use space or line continuation characters.
                    target_pin = pin.linked_pins[0]
                    target_node = self.parser.get_node_by_guid(target_pin.node_guid)
                    if target_node:
                        branch_lines = self.trace_path(target_node, processed_guids_in_path.copy(), processed_globally, next_indent_prefix_branch, is_last_branch) # Pass is_last_branch correctly
                        lines.extend(branch_lines)
                    else:
                        lines.append(f"{next_indent_prefix_branch}{self.exec_prefix}[Branch '{label}' leads to missing node: {target_pin.node_guid[:8]}]")

            if handled_as_branch:
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Branching handled for node {current_guid}.", file=sys.stderr)
                current_node = None # Stop linear traversal after handling branches
                break # Exit while loop

            # --- Standard Linear Continuation ---
            # This only runs if the node was NOT handled as a branch
            # Determine the correct prefix for the *next* node in the linear path
            # The next indent uses spaces if the current segment is the last, otherwise lines.
            next_linear_indent = indent_prefix + (self.indent_space if is_last_segment else self.line_cont)
            next_node_in_path = self._find_next_executable_node(current_node, lines, next_linear_indent, primary_exec_output)

            # If _find_next returned None, the path ended (message was added by helper if appropriate)
            if next_node_in_path is None:
                if not handled_as_branch and not isinstance(current_node, K2Node_FunctionResult):
                    # Check if the primary exec output existed but was unlinked
                    primary_output = primary_exec_output if primary_exec_output else current_node.get_execution_output_pin()
                    if primary_output and not primary_output.linked_pins:
                         lines.append(f"{next_linear_indent}{self.exec_prefix}[Path ends: Pin '{primary_output.name}' unlinked]")
                         if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Linear path ends, pin '{primary_output.name}' unlinked.", file=sys.stderr)
                    elif not primary_output:
                        lines.append(f"{next_linear_indent}{self.exec_prefix}[Path ends: No primary execution output pin found]")
                        if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Linear path ends, no output pin.", file=sys.stderr)
                    # else: message might have been added by _find_next already if it hit depth limit etc.

                break # Exit while loop

            # Otherwise, continue the loop with the next node and updated indent
            current_node = next_node_in_path
            indent_prefix = next_linear_indent # Update indent_prefix for the next iteration
            is_first_node_in_call = False # No longer the first node

        # --- End of While Loop ---

        if depth >= max_depth:
            lines.append(f"{indent_prefix}{self.exec_prefix}[Trace depth limit reached ({max_depth})]")
            if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop: Max depth reached.", file=sys.stderr)

        if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}TRACE PATH END: Node={self._get_node_ref_name(start_node)}. Returning {len(lines)} lines.", file=sys.stderr)
        return lines


    # --- Modified _find_next_executable_node slightly to pass indent_prefix ---
    def _find_next_executable_node(self, current_node: Node, lines: List[str], indent_prefix: str, primary_exec_pin: Optional[Pin] = None) -> Optional[Node]:
        """
        Finds the next non-pure, non-comment, non-knot node following the execution or data path.
        Avoids simple loops involving only knots/pure nodes.
        Does NOT add end-of-path messages itself, relies on trace_path to determine the end reason.
        """
        search_depth = 0
        max_search_depth = 15 # Limit search depth to avoid infinite loops in pure/knot chains
        temp_node = current_node
        # Track nodes visited *within this specific search* to avoid simple knot loops
        visited_in_search = {current_node.guid}

        while search_depth < max_search_depth:
            search_depth += 1
            next_pin: Optional[Pin] = None

            # Determine the pin to follow based on node type
            if isinstance(temp_node, K2Node_Knot):
                 next_pin = temp_node.get_passthrough_output_pin()
                 if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  (Searching from Knot {self._get_node_ref_name(temp_node)}, using passthrough output: {next_pin.name if next_pin else 'None'})")
            elif temp_node.is_pure():
                 # For pure nodes, we try to follow a meaningful output data pin
                 output_pins = temp_node.get_output_pins(include_hidden=False)
                 if output_pins:
                     # Prioritize 'ReturnValue' or the first non-hidden pin
                     next_pin = temp_node.get_pin("ReturnValue") or output_pins[0]
                     if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  (Searching from Pure node {self._get_node_ref_name(temp_node)}, using data output: {next_pin.name if next_pin else 'None'})")
                 else:
                     if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  (Stopping search at pure node {self._get_node_ref_name(temp_node)} - no output pins)")
                     return None # Pure node with no outputs ends this search path
            else:
                # Use the primary exec pin if provided (e.g., from specific branch logic)
                # otherwise, find the default exec output for standard executable nodes
                next_pin = primary_exec_pin if primary_exec_pin else temp_node.get_execution_output_pin()
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  (Searching from Exec node {self._get_node_ref_name(temp_node)}, using output pin: {next_pin.name if next_pin else 'None'})")


            if not next_pin:
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop Search: Node {self._get_node_ref_name(temp_node)} has no relevant output pin to follow.", file=sys.stderr)
                return None

            if not next_pin.linked_pins:
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop Search: Pin {next_pin.name} on {self._get_node_ref_name(temp_node)} is unlinked.", file=sys.stderr)
                return None

            # Execution pins should only have one link, but data pins might have multiple.
            # Prioritize finding an executable node first across all links.
            found_executable_target: Optional[Node] = None
            next_temp_node_candidate: Optional[Node] = None # Store the first pure/knot candidate found

            for target_pin in next_pin.linked_pins:
                candidate_node = self.parser.get_node_by_guid(target_pin.node_guid)

                if not candidate_node:
                     if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop Search: Linked node {target_pin.node_guid} missing.", file=sys.stderr)
                     continue # Check other links if any

                # Check if it's the next *executable* node
                if not candidate_node.is_pure() and not isinstance(candidate_node, (K2Node_Knot, EdGraphNode_Comment)):
                     found_executable_target = candidate_node
                     if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Found Next Executable: {self._get_node_ref_name(candidate_node)} via pin {next_pin.name}", file=sys.stderr)
                     break # Found the best target, stop checking other links from this pin

                # If not executable, check if it's a knot or pure node we can traverse through
                elif not isinstance(candidate_node, EdGraphNode_Comment):
                     # Check for loops *within this search*
                     if candidate_node.guid in visited_in_search:
                         if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Skip Link: Loop detected during pure/knot search at {self._get_node_ref_name(candidate_node)}.", file=sys.stderr)
                         continue # Avoid simple loops

                     # Store the first valid pure/knot candidate we find, but keep looking for an executable one
                     if next_temp_node_candidate is None:
                        if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Candidate Pure/Knot: {self._get_node_ref_name(candidate_node)}", file=sys.stderr)
                        next_temp_node_candidate = candidate_node
                        visited_in_search.add(candidate_node.guid) # Mark as visited for loop detection

                else: # It's a comment node, ignore it for path traversal
                    if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Skip Link: Target is comment node {self._get_node_ref_name(candidate_node)}.", file=sys.stderr)
                    continue

            # After checking all links for the current pin:
            if found_executable_target:
                return found_executable_target # Return the executable node immediately

            # If no executable node was found, but we have a pure/knot candidate, continue searching from it
            if next_temp_node_candidate:
                temp_node = next_temp_node_candidate
                if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Traversing to Pure/Knot: {self._get_node_ref_name(temp_node)}", file=sys.stderr)
                continue # Continue the while loop from this new node

            # If we checked all links and found neither an executable node nor a pure/knot node to continue from
            if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop Search: No further valid nodes found from {self._get_node_ref_name(temp_node)} pin '{next_pin.name}'.", file=sys.stderr)
            return None


        # Max search depth reached while skipping pure/knots
        if ENABLE_PATH_TRACER_DEBUG: print(f"{indent_prefix}  -> Stop Search: Max search depth ({max_search_depth}) reached while skipping pure/knots from {self._get_node_ref_name(current_node)}.", file=sys.stderr)
        # lines.append(f"{indent_prefix}{self.exec_prefix}[Trace depth limit reached ({max_search_depth}) while skipping intermediate nodes]") # Optionally add message here or let trace_path handle it
        return None

    # _trace_branch is removed as its logic is integrated into trace_path