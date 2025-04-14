# --- START OF FILE blueprint_parser/formatter/node_formatter.py ---

import re
from typing import Dict, Optional, Set, Tuple, List
import sys
# --- Use relative import ---
from ..nodes import (Node, Pin, K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction,
                     K2Node_VariableSet, K2Node_VariableGet, K2Node_IfThenElse, K2Node_ExecutionSequence, K2Node_FlipFlop,
                     K2Node_DynamicCast, K2Node_AddDelegate, K2Node_AssignDelegate, K2Node_RemoveDelegate, K2Node_ClearDelegate,
                     K2Node_CallFunction, K2Node_MacroInstance, K2Node_CallDelegate,
                     K2Node_PromotableOperator, K2Node_CommutativeAssociativeBinaryOperator,
                     K2Node_Select, K2Node_MakeStruct, K2Node_BreakStruct, K2Node_SetFieldsInStruct,
                     K2Node_Switch, K2Node_ForEachLoop, K2Node_CallParentFunction, K2Node_SwitchEnum,
                     K2Node_Timeline, K2Node_InputAction, K2Node_InputAxisEvent, K2Node_InputKey, K2Node_InputTouch,
                     K2Node_InputAxisKeyEvent, K2Node_InputDebugKey, K2Node_LatentAction,K2Node_GetArrayItem,
                     K2Node_SpawnActorFromClass, K2Node_AddComponent, K2Node_CreateWidget, K2Node_GenericCreateObject,
                     K2Node_CallArrayFunction, K2Node_MakeArray, K2Node_MakeMap, K2Node_GetClassDefaults,
                     K2Node_FormatText, K2Node_GetSubsystem, K2Node_PlayMontage, K2Node_CreateDelegate, K2Node_FunctionResult,
                     K2Node_FunctionEntry,
                     # --- ADDED IMPORTS ---
                     K2Node_Literal, K2Node_ComponentBoundEvent, K2Node_ActorBoundEvent,
                     K2Node_Composite)
# --- Use relative import ---
from .data_tracer import DataTracer # Import DataTracer class
# --- Use relative import ---
from ..utils import extract_simple_name_from_path, extract_member_name

ENABLE_NODE_FORMATTER_DEBUG = False
# Use global debug flag potentially defined elsewhere (e.g., in parser)
ENABLE_PARSER_DEBUG = False # Assume False unless set globally

# --- Helper to wrap text in span ---
def span(css_class: str, text: str) -> str:
    """Consistently wrap text in a span with the given CSS class."""
    # Basic escaping to prevent HTML injection
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return f'<span class="{css_class}">{text}</span>'

class NodeFormatter:
    """Formats nodes into Markdown, including spans for highlighting."""
    def __init__(self, parser, data_tracer: DataTracer): # Takes parser and data_tracer
        self.parser = parser
        self.data_tracer = data_tracer

    def _format_target(self, target_str: str) -> str:
        """Formats the target string, wrapping complex targets."""
        if target_str == span("bp-var", "`self`"):
            return "" # Implicit self
        elif re.match(r'^<span class="bp-var">`[a-zA-Z0-9_]+`</span>$', target_str) and '.' not in target_str:
              return f" on {target_str}" # Simple variable target
        else:
            # Wrap complex expressions or function calls in parentheses visually
            return f" on ({target_str})"

    # --- MODIFIED: Calls trace_pin_value with Pin object ---
    def _format_arguments(self, node: Node, visited_data_pins: Set[str], exclude_pins: Optional[Set[str]] = None) -> str:
        """Formats arguments as (Name=Value, ...) string, skipping trivial/implicit/excluded."""
        if exclude_pins is None: exclude_pins = set()
        args_list = []
        implicit_pins = {'self', 'target', 'worldcontextobject', '__worldcontext', 'latentinfo'}
        exclude_pins.update(implicit_pins)

        sorted_pins = node.get_input_pins(exclude_exec=True, include_hidden=True)

        has_advanced_inputs = any(p.is_advanced_view() for p in sorted_pins)
        show_advanced = has_advanced_inputs and any(
            p.is_advanced_view() and (p.linked_pins or not self.data_tracer._is_trivial_default(p))
            for p in sorted_pins
        )

        for pin in sorted_pins:
            pin_name_lower = (pin.name or "").lower()
            if pin_name_lower in exclude_pins or pin.is_hidden() or (pin.is_advanced_view() and not show_advanced):
                continue
            try:
                if pin.linked_pins or not self.data_tracer._is_trivial_default(pin):
                    # !!! Pass the Pin object, not just the ID !!!
                    pin_val_raw = self.data_tracer.trace_pin_value(pin, visited_pins=visited_data_pins.copy())
                    # Wrap pin name and value appropriately
                    pin_name_span = span("bp-param-name", f"`{pin.name}`")
                    # Value might already contain spans from deeper tracing
                    args_list.append(f"{pin_name_span}={pin_val_raw}")
            except Exception as e:
                print(f"ERROR: Error tracing argument pin `{pin.name}` on node {node.guid}: {e}", file=sys.stderr)
                # Print full traceback for argument tracing errors if debug enabled
                if ENABLE_NODE_FORMATTER_DEBUG:
                    import traceback
                    traceback.print_exc()
                pin_name_span = span("bp-param-name", f"`{pin.name}`")
                args_list.append(f"{pin_name_span}={span('bp-error', '[Trace Error]')}")

        return f"({', '.join(args_list)})" if args_list else ""
    # ----------------------------------------------------


    def format_node(self, node: Node, prefix: str, visited_data_pins: Set[str]) -> Tuple[Optional[str], Optional[Pin]]:
        """Formats a node into Markdown, returns (description, primary_output_exec_pin)."""
        # --- MODIFIED: Call _format_literal_node which can return None ---
        formatter_func = self._get_formatter_func(node)
        desc: Optional[str] = None
        try:
            # Pass a copy of visited_data_pins to isolate data tracing for this node's arguments
            desc = formatter_func(node, visited_data_pins.copy())
        except Exception as e:
            import traceback
            print(f"ERROR formatting node {node.guid} ({node.node_type}): {e}", file=sys.stderr)
            if ENABLE_NODE_FORMATTER_DEBUG or ENABLE_PARSER_DEBUG: traceback.print_exc() # Use global debug flag potentially
            desc = f"{span('bp-error', '**ERROR Formatting Node**')} {span('bp-node-type', f'`{node.node_type}`')}"

        # If the formatter returned None (e.g., for pure or literal nodes), we don't trace from it.
        if desc is None:
            # if ENABLE_NODE_FORMATTER_DEBUG: print(f"DEBUG (NodeFormatter): Skipping pure/literal node formatting: {node.name or node.guid} ({node.node_type})", file=sys.stderr)
            return None, None

        primary_exec_output = node.get_execution_output_pin()
        return desc, primary_exec_output


    # --- MODIFIED: Add Literal, Bound Events, Composite ---
    def _get_formatter_func(self, node: Node) -> callable:
        if isinstance(node, K2Node_Literal): return self._format_literal_node # NEW
        # --- MODIFIED: Include Bound Events ---
        if isinstance(node, (K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction, K2Node_InputAction,
                              K2Node_InputAxisEvent, K2Node_InputKey, K2Node_InputTouch, K2Node_InputAxisKeyEvent,
                              K2Node_InputDebugKey, K2Node_FunctionEntry, K2Node_ComponentBoundEvent, K2Node_ActorBoundEvent)):
            return self._format_event
        # --- END MODIFICATION ---
        if isinstance(node, K2Node_VariableSet): return self._format_variable_set
        if isinstance(node, K2Node_CallFunction): return self._format_call_function
        if isinstance(node, K2Node_MacroInstance): return self._format_macro_instance
        if isinstance(node, K2Node_IfThenElse): return self._format_if
        if isinstance(node, K2Node_ExecutionSequence): return self._format_sequence
        if isinstance(node, K2Node_FlipFlop): return self._format_flipflop
        if isinstance(node, K2Node_DynamicCast): return self._format_dynamic_cast
        if isinstance(node, K2Node_AddDelegate): return self._format_add_delegate
        if isinstance(node, K2Node_AssignDelegate): return self._format_assign_delegate
        if isinstance(node, K2Node_RemoveDelegate): return self._format_remove_delegate
        if isinstance(node, K2Node_ClearDelegate): return self._format_clear_delegate
        if isinstance(node, K2Node_CallDelegate): return self._format_call_delegate
        if isinstance(node, K2Node_Switch): return self._format_switch
        if isinstance(node, K2Node_ForEachLoop): return self._format_foreach_loop
        if isinstance(node, K2Node_CallParentFunction): return self._format_call_parent_function
        if isinstance(node, K2Node_Timeline): return self._format_timeline
        if isinstance(node, K2Node_SetFieldsInStruct): return self._format_set_fields_in_struct
        if isinstance(node, K2Node_FunctionResult): return self._format_return_node
        if isinstance(node, K2Node_SpawnActorFromClass): return self._format_spawn_actor
        if isinstance(node, K2Node_AddComponent): return self._format_add_component
        if isinstance(node, K2Node_CreateWidget): return self._format_create_widget
        if isinstance(node, K2Node_GenericCreateObject): return self._format_generic_create_object
        if isinstance(node, K2Node_CallArrayFunction): return self._format_call_array_function # ADDED Line
        if isinstance(node, K2Node_FormatText): return self._format_format_text
        if isinstance(node, K2Node_PlayMontage): return self._format_play_montage
        if isinstance(node, K2Node_LatentAction): return self._format_latent_action
        if isinstance(node, K2Node_Composite): return self._format_composite # NEW
        return self._format_generic

    # --- NEW: Format Literal Node (Often skipped visually) ---
    def _format_literal_node(self, node: K2Node_Literal, visited_data_pins: Set[str]) -> Optional[str]:
        # Literal nodes usually don't appear directly in the execution flow trace,
        # their value is resolved by the DataTracer when tracing pins connected to them.
        # Return None so the PathTracer skips showing it as a separate execution step.
        if ENABLE_NODE_FORMATTER_DEBUG: print(f"DEBUG (NodeFormatter): Skipping visual format for Literal Node {node.guid[:4]}", file=sys.stderr)
        return None

    # --- MODIFIED: Add Bound Event Handling ---
    def _format_event(self, node: Node, visited_data_pins: Set[str]) -> str:
        name = "Unknown Event"; keyword = span("bp-keyword", "**Event**"); args_list = []
        # Extract standard event/input args_list from output data pins
        output_data_pins = node.get_output_pins(include_hidden=False)
        for pin in output_data_pins:
            if not pin.is_execution():
                pin_type_sig = pin.get_type_signature()
                pin_type_span = span("bp-data-type", f":`{pin_type_sig}`") if pin_type_sig else ""
                args_list.append(f"{span('bp-param-name', f'`{pin.name}`')}{pin_type_span}")
        args_str = f" Args:({', '.join(args_list)})" if args_list else ""

        # --- ADDED Bound Event Logic ---
        if isinstance(node, K2Node_ComponentBoundEvent):
            # Use properties set during parsing finalize step
            delegate_name = node.delegate_property_name or "?Delegate?"
            comp_name = node.component_property_name or "?Component?"
            owner_class = extract_simple_name_from_path(node.delegate_owner_class) or "?"
            # Format the name string, applying spans
            name = f"{span('bp-delegate-name', f'`{delegate_name}`')} ({span('bp-component-name', f'`{comp_name}`')} on {span('bp-class-name', f'`{owner_class}`')})"
            keyword = span("bp-keyword", "**Bound Event**")
            # Clear args_str as output pins are usually just 'OutputDelegate' which isn't a data param
            args_str = ""
        elif isinstance(node, K2Node_ActorBoundEvent):
            delegate_name = node.delegate_property_name or "?Delegate?"
            # Format the name string, applying spans
            name = f"{span('bp-delegate-name', f'`{delegate_name}`')}"
            keyword = span("bp-keyword", "**Actor Bound Event**")
            # Clear args_str
            args_str = ""
        # --- END ADDED ---
        elif isinstance(node, K2Node_CustomEvent):
            name = node.custom_function_name or "Unnamed Custom"
            keyword = span("bp-keyword", "**Custom Event**")
        elif isinstance(node, K2Node_EnhancedInputAction):
            name = node.input_action_name or "Unnamed Action"
            keyword = span("bp-keyword", "**Input Action**")
        elif isinstance(node, K2Node_InputAction):
            name = node.action_name or "Unnamed Legacy Action"
            keyword = span("bp-keyword", "**Input Action (Legacy)**")
        elif isinstance(node, K2Node_InputAxisEvent):
            name = node.axis_name or "Unnamed Axis"
            keyword = span("bp-keyword", "**Input Axis (Legacy)**")
        elif isinstance(node, K2Node_InputKey):
            name = node.input_key_name or "Unnamed Key"
            keyword = span("bp-keyword", "**Input Key (Legacy)**")
        elif isinstance(node, K2Node_InputTouch):
            name = "Touch"
            keyword = span("bp-keyword", "**Input Touch (Legacy)**")
        elif isinstance(node, K2Node_InputAxisKeyEvent):
            name = node.axis_key_name or "Unnamed Axis Key"
            keyword = span("bp-keyword", "**Input Axis Key (Legacy)**")
        elif isinstance(node, K2Node_InputDebugKey):
            name = node.input_key_name or "Unnamed Debug Key"
            keyword = span("bp-keyword", "**Input Debug Key (Legacy)**")
        elif isinstance(node, K2Node_FunctionEntry):
            func_ref = node.raw_properties.get("FunctionReference")
            name = extract_member_name(func_ref) or "Unnamed Function Entry"
            keyword = span("bp-keyword", "**Function Entry**")
        elif isinstance(node, K2Node_Event):
            name = node.event_function_name or "Unnamed Event"
            name_map = {"ReceiveBeginPlay": "Begin Play", "ReceiveTick": "Tick", "ReceiveAnyDamage": "Any Damage",
                        "ReceiveEndPlay": "End Play", "ReceiveDestroyed": "Destroyed",
                        "OnComponentBeginOverlap": "Component Begin Overlap", "OnComponentEndOverlap": "Component End Overlap",
                        "OnActorBeginOverlap": "Actor Begin Overlap", "OnActorEndOverlap": "Actor End Overlap",
                        "OnTakeAnyDamage": "Take Any Damage", "ReceiveDrawHUD": "Draw HUD"}
            name = name_map.get(name, name)
            keyword = span("bp-keyword", "**Event**")

        # Format name with span unless already formatted by Bound Event logic
        name_span = span("bp-event-name", f"`{name}`") if not isinstance(node, (K2Node_ComponentBoundEvent, K2Node_ActorBoundEvent)) else name
        return f"{keyword} {name_span}{args_str}"


    def _format_variable_set(self, node: K2Node_VariableSet, visited_data_pins: Set[str]) -> str:
        var_name = node.variable_name or "UnknownVar"; value_pin = node.get_value_input_pin(); target_pin = node.get_target_pin()
        target_str_raw = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy())
        value_str_raw = self.data_tracer.trace_pin_value(value_pin, visited_pins=visited_data_pins.copy()) if value_pin else span("bp-error", "<?>") # Pass Pin object
        var_type_sig = node.variable_type or (value_pin.get_type_signature() if value_pin else None)
        var_type_span = span("bp-data-type", f":`{var_type_sig}`") if var_type_sig else ""
        target_fmt = self._format_target(target_str_raw) # This already returns spans
        keyword = span("bp-keyword", "**Set**")
        var_name_span = span("bp-var", f"`{var_name}`")
        return f"{keyword} {var_name_span}{var_type_span} = {value_str_raw}{target_fmt}"

    # --- START OF MODIFIED _format_call_function ---
    def _format_call_function(self, node: K2Node_CallFunction, visited_data_pins: Set[str]) -> str:
        raw_func_name = node.function_name or 'UnknownFunction'

        # --- ADD K2NODE_ PREFIX REMOVAL ---
        func_name = raw_func_name
        if func_name.startswith("K2Node_"):
            func_name = func_name[len("K2Node_"):]
        # --- END PREFIX REMOVAL ---

        target_pin = node.get_target_pin()
        target_str_raw = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy())
        args_str = self._format_arguments(node, visited_data_pins.copy())
        latent_info = span("bp-modifier", " [(Latent)]") if node.is_latent else ""
        dev_only = span("bp-modifier", " [(Dev Only)]") if getattr(node, 'is_dev_only', False) else ""
        return_pin = next((p for p in node.get_output_pins() if not p.is_execution() and p.name == "ReturnValue"), None)
        return_type_sig = return_pin.get_type_signature() if return_pin else None
        return_type = span("bp-data-type", f" -> `{return_type_sig}`") if return_type_sig else ""

        # Use the cleaned func_name
        func_name_span = span("bp-func-name", f"`{func_name}`")

        # Determine if this is a static call (using cleaned target logic from previous steps)
        is_static_call = False
        if target_str_raw:
            # Regex to match various forms of class/default object references, excluding 'self'
            match_class_default = re.match(r'^(?:<span class="bp-var">)?`?([a-zA-Z0-9_]+)`?(?:</span>)?(?:|::(?:<span class="bp-keyword">)?Default(?:</span>)?)?$', target_str_raw)
            match_class_only = re.match(r'^<span class="bp-class-name">`([a-zA-Z0-9_]+)`</span>$', target_str_raw)
            match_object_path = re.match(r'^<span class="bp-literal-object">`([a-zA-Z0-9_/.:]+)`</span>$', target_str_raw)

            # More robust check for static calls based on target format
            if (match_class_default and match_class_default.group(1) != 'self') or \
               (match_class_only and match_class_only.group(1) != 'self') or \
               (match_object_path and match_object_path.group(1) != 'self' and 'Default__' in match_object_path.group(1)) or \
               target_str_raw.startswith(span("bp-var", "`Default__")): # Direct check for Default__ prefix
                 is_static_call = True


        if is_static_call:
            keyword = span("bp-keyword", "**Static Call**")
            # Extract class name for static call formatting
            class_name_span_str = ""
            # Decode HTML entities potentially introduced by span() before regex matching
            target_cleaned = target_str_raw.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>')
            # Regex to extract class name from various static target formats
            class_name_match = re.match(r'^(?:<span class="(?:bp-var|bp-literal-object)">)?`?(?:Default__)?([a-zA-Z0-9_]+)`?(?:</span>)?(?:|::(?:<span class="bp-keyword">)?Default(?:</span>)?)?$', target_cleaned)
            class_only_match = re.match(r'^<span class="bp-class-name">`([a-zA-Z0-9_]+)`</span>$', target_cleaned)

            class_name = None
            if class_name_match: class_name = class_name_match.group(1)
            elif class_only_match: class_name = class_only_match.group(1)

            # Optionally add ClassName.FunctionName if the class isn't a common library
            if class_name and class_name not in ['KismetSystemLibrary', 'KismetMathLibrary', 'GameplayStatics', 'KismetStringLibrary', 'KismetArrayLibrary']:
                 class_name_span_str = f"{span('bp-class-name', f'`{class_name}`')}." # Note the added dot

            return f"{keyword} {class_name_span_str}{func_name_span}{args_str}{return_type}{latent_info}{dev_only}"
        else:
            keyword = span("bp-keyword", "**Call**")
            target_fmt = self._format_target(target_str_raw)
            return f"{keyword} {func_name_span}{args_str}{target_fmt}{return_type}{latent_info}{dev_only}"
    # --- END OF MODIFIED _format_call_function ---


    def _format_call_parent_function(self, node: K2Node_CallParentFunction, visited_data_pins: Set[str]) -> str:
        func_name = node.parent_function_name or (node.function_name or 'UnknownFunction')
        args_str = self._format_arguments(node, visited_data_pins.copy())
        keyword = span("bp-keyword", "**Call Parent**")
        func_name_span = span("bp-func-name", f"`{func_name}`")
        return f"{keyword} {func_name_span}{args_str}"

    def _format_macro_instance(self, node: K2Node_MacroInstance, visited_data_pins: Set[str]) -> str:
        macro_name = node.macro_type or "Unknown Macro"
        keyword = span("bp-keyword", f"**{macro_name}**") # Use macro type as keyword base
        # Handle specific known macros for better descriptions
        if node.macro_type == "FlipFlop": return keyword
        if node.macro_type == "Gate":
            is_open_pin = node.get_pin(pin_name="IsOpen")
            is_open_val = self.data_tracer.trace_pin_value(is_open_pin, visited_pins=visited_data_pins.copy()) if is_open_pin else span("bp-error", "<?>")
            return f"{keyword} (IsOpen={is_open_val})"
        if node.macro_type == "IsValid":
            input_pin = node.get_pin(pin_name="Input Object") or node.get_pin(pin_name="inObject") or node.get_pin(pin_name="In")
            input_val = self.data_tracer.trace_pin_value(input_pin, visited_pins=visited_data_pins.copy()) if input_pin else span("bp-error", "<?>")
            return f"{keyword} ({input_val})"
        if node.macro_type in ("ForEachLoop", "ForEachLoopWithBreak"):
            array_pin = node.get_pin(pin_name="Array")
            array_val = self.data_tracer.trace_pin_value(array_pin, visited_pins=visited_data_pins.copy()) if array_pin else span("bp-error", "<?>")
            elem_pin = node.get_pin("Array Element")
            idx_pin = node.get_pin("Array Index")
            elem_type = elem_pin.get_type_signature() if elem_pin else '?'
            idx_type = idx_pin.get_type_signature() if idx_pin else '?'
            elem_str = f" Element:{span('bp-data-type', f'`{elem_type}`')}" if elem_pin else ""
            idx_str = f", Index:{span('bp-data-type', f'`{idx_type}`')}" if idx_pin else ""
            return f"{keyword} in ({array_val}) [{elem_str}{idx_str} ]"
        if node.macro_type in ("ForLoop", "ForLoopWithBreak"):
            first_idx_pin = node.get_pin(pin_name="First Index") or node.get_pin(pin_name="FirstIndex")
            last_idx_pin = node.get_pin(pin_name="Last Index") or node.get_pin(pin_name="LastIndex")
            first_val = self.data_tracer.trace_pin_value(first_idx_pin, visited_pins=visited_data_pins.copy()) if first_idx_pin else span("bp-error", "<?>")
            last_val = self.data_tracer.trace_pin_value(last_idx_pin, visited_pins=visited_data_pins.copy()) if last_idx_pin else span("bp-error", "<?>")
            return f"{keyword} (Index from {first_val} to {last_val})"
        if node.macro_type == "WhileLoop":
            cond_pin = node.get_pin(pin_name="Condition")
            cond_val = self.data_tracer.trace_pin_value(cond_pin, visited_pins=visited_data_pins.copy()) if cond_pin else span("bp-error", "<?>")
            return f"{keyword} (Condition={cond_val})"
        if node.macro_type == "DoN":
            n_pin = node.get_pin(pin_name="N")
            n_val = self.data_tracer.trace_pin_value(n_pin, visited_pins=visited_data_pins.copy()) if n_pin else span("bp-error", "<?>")
            return f"{keyword} (N={n_val})"
        if node.macro_type == "DoOnce": return keyword
        if node.macro_type == "MultiGate": return keyword

        # Default macro formatting
        args_str = self._format_arguments(node, visited_data_pins.copy()) # Already includes spans
        macro_name_span = span("bp-macro-name", f"`{macro_name}`")
        keyword = span("bp-keyword", "**Macro**") # Generic keyword
        return f"{keyword} {macro_name_span}{args_str}"

    def _format_if(self, node: K2Node_IfThenElse, visited_data_pins: Set[str]) -> str:
        condition_pin = node.get_condition_pin()
        condition_str_raw = self.data_tracer.trace_pin_value(condition_pin, visited_pins=visited_data_pins.copy()) if condition_pin else span("bp-error", "<?>")
        keyword = span("bp-keyword", "**If**")
        return f"{keyword} ({condition_str_raw})"

    def _format_sequence(self, node: K2Node_ExecutionSequence, visited_data_pins: Set[str]) -> str:
        return span("bp-keyword", "**Sequence**")

    def _format_flipflop(self, node: K2Node_FlipFlop, visited_data_pins: Set[str]) -> str:
        return span("bp-keyword", "**FlipFlop**")

    # --- START OF MODIFIED _format_dynamic_cast with DEBUG ---
    def _format_dynamic_cast(self, node: K2Node_DynamicCast, visited_data_pins: Set[str]) -> str:
        object_pin = node.get_object_pin()
        object_str_raw = self.data_tracer.trace_pin_value(object_pin, visited_pins=visited_data_pins.copy()) if object_pin else span("bp-error", "<?>")

        # --- DEBUG START ---
        if ENABLE_NODE_FORMATTER_DEBUG: print(f"DEBUG [Cast Format {node.name}]: Starting type resolution.", file=sys.stderr)
        # --- END DEBUG ---

        cast_type_name = "UnknownType"
        as_pin = node.get_as_pin()
        as_pin_type_path = None
        # Use the raw property directly, fallback to parsed node.target_type if needed
        target_type_path_prop = node.raw_properties.get("TargetType")

        # --- DEBUG START ---
        if ENABLE_NODE_FORMATTER_DEBUG: print(f"DEBUG [Cast Format {node.name}]: AsPin found: {as_pin is not None}", file=sys.stderr)
        if as_pin:
            if ENABLE_NODE_FORMATTER_DEBUG: print(f"DEBUG [Cast Format {node.name}]: AsPin SubCategoryObject: {as_pin.sub_category_object}", file=sys.stderr)
        if ENABLE_NODE_FORMATTER_DEBUG: print(f"DEBUG [Cast Format {node.name}]: TargetType Property: {target_type_path_prop}", file=sys.stderr)
        # --- END DEBUG ---

        if as_pin and as_pin.sub_category_object:
            as_pin_type_path = str(as_pin.sub_category_object).strip("'\"") # Ensure string and clean quotes
            # Check if the 'As...' pin type is specific enough
            if as_pin_type_path and as_pin_type_path.lower() != '/script/coreuobject.class':
                resolved_name = extract_simple_name_from_path(as_pin_type_path)
                if resolved_name:
                    cast_type_name = resolved_name
                    # --- DEBUG START ---
                    if ENABLE_NODE_FORMATTER_DEBUG: print(f"DEBUG [Cast Format {node.name}]: Type set from AsPin: {cast_type_name}", file=sys.stderr)
                    # --- END DEBUG ---

        # If 'As...' pin didn't give a specific type, try the TargetType property
        if cast_type_name == "UnknownType" and target_type_path_prop:
            target_type_path_str = str(target_type_path_prop).strip("'\"")
            resolved_name = extract_simple_name_from_path(target_type_path_str)
            if resolved_name and resolved_name.lower() != 'class': # Avoid using generic 'Class'
                cast_type_name = resolved_name
                # --- DEBUG START ---
                if ENABLE_NODE_FORMATTER_DEBUG: print(f"DEBUG [Cast Format {node.name}]: Type set from TargetType Prop: {cast_type_name}", file=sys.stderr)
                # --- END DEBUG ---

        # Final fallback if both fail (using the potentially generic node.target_type parsed earlier)
        if cast_type_name == "UnknownType":
            if node.target_type: # Use the value finalized onto the node object
               cast_type_name = node.target_type
               # --- DEBUG START ---
               if ENABLE_NODE_FORMATTER_DEBUG: print(f"DEBUG [Cast Format {node.name}]: Type set from node.target_type fallback: {cast_type_name}", file=sys.stderr)
               # --- END DEBUG ---
            else:
                # --- DEBUG START ---
                if ENABLE_NODE_FORMATTER_DEBUG: print(f"DEBUG [Cast Format {node.name}]: All checks failed, using 'UnknownType'.", file=sys.stderr)
                # --- END DEBUG ---
                cast_type_name = "UnknownType" # Ensure it remains UnknownType

        cast_type_span = span("bp-data-type", f"`{cast_type_name}`")
        as_pin_str = f" (as {span('bp-param-name', f'`{as_pin.name}`')})" if as_pin and as_pin.name else ""

        keyword = span("bp-keyword", "**Cast**")
        return f"{keyword} ({object_str_raw}) To {cast_type_span}{as_pin_str}"
    # --- END OF MODIFIED _format_dynamic_cast with DEBUG ---


    def _format_delegate_binding(self, node: Node, visited_data_pins: Set[str], action: str) -> str:
        delegate_prop_name = node.delegate_name or "?Delegate?"
        target_pin = node.get_target_pin()
        delegate_input_pin = node.get_delegate_pin()
        target_str_raw = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy()) if target_pin else span("bp-var", "`self`")
        event_str_raw = self.data_tracer.trace_pin_value(delegate_input_pin, visited_pins=visited_data_pins.copy()) if delegate_input_pin else span("bp-error", "*(Unlinked Delegate Input)*")
        target_fmt = self._format_target(target_str_raw)
        keyword = span("bp-keyword", f"**{action}**")
        delegate_name_span = span("bp-delegate-name", f"`{delegate_prop_name}`")
        return f"{keyword} Delegate {delegate_name_span} to {event_str_raw}{target_fmt}"

    def _format_add_delegate(self, node: K2Node_AddDelegate, visited_data_pins: Set[str]) -> str:
        return self._format_delegate_binding(node, visited_data_pins, "Bind")

    def _format_assign_delegate(self, node: K2Node_AssignDelegate, visited_data_pins: Set[str]) -> str:
        return self._format_delegate_binding(node, visited_data_pins, "Assign")

    def _format_remove_delegate(self, node: K2Node_RemoveDelegate, visited_data_pins: Set[str]) -> str:
        return self._format_delegate_binding(node, visited_data_pins, "Unbind")

    def _format_clear_delegate(self, node: K2Node_ClearDelegate, visited_data_pins: Set[str]) -> str:
        delegate_prop_name = node.delegate_name or "?Delegate?"
        target_pin = node.get_target_pin()
        target_str_raw = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy()) if target_pin else span("bp-var", "`self`")
        target_fmt = self._format_target(target_str_raw)
        keyword = span("bp-keyword", "**Unbind All**")
        delegate_name_span = span("bp-delegate-name", f"`{delegate_prop_name}`")
        return f"{keyword} from Delegate {delegate_name_span}{target_fmt}"

    def _format_call_delegate(self, node: K2Node_CallDelegate, visited_data_pins: Set[str]) -> str:
        delegate_name = node.delegate_name or 'UnknownDelegate'
        target_pin = node.get_target_pin()
        target_str_raw = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy())
        args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins={'delegate'})
        target_fmt = self._format_target(target_str_raw)
        keyword = span("bp-keyword", "**Call Delegate**")
        delegate_name_span = span("bp-delegate-name", f"`{delegate_name}`")
        return f"{keyword} {delegate_name_span}{args_str}{target_fmt}"

    def _format_switch(self, node: K2Node_Switch, visited_data_pins: Set[str]) -> str:
        selection_pin = node.get_selection_pin()
        selection_str_raw = self.data_tracer.trace_pin_value(selection_pin, visited_pins=visited_data_pins.copy()) if selection_pin else span("bp-error", "<?>")
        switch_type = ""
        if isinstance(node, K2Node_SwitchEnum):
            switch_type = f" on Enum {span('bp-data-type', f'`{node.enum_type}`')}" if node.enum_type else " on Enum"
        elif selection_pin and selection_pin.category != 'exec':
            switch_type = f" on {span('bp-data-type', f'`{selection_pin.get_type_signature()}`')}"
        keyword = span("bp-keyword", "**Switch**")
        return f"{keyword} ({selection_str_raw}){switch_type}"

    def _format_foreach_loop(self, node: K2Node_ForEachLoop, visited_data_pins: Set[str]) -> str:
        array_pin = node.get_array_pin()
        array_val_raw = self.data_tracer.trace_pin_value(array_pin, visited_pins=visited_data_pins.copy()) if array_pin else span("bp-error", "<?>")
        elem_pin = node.get_array_element_pin()
        idx_pin = node.get_array_index_pin()
        elem_type = elem_pin.get_type_signature() if elem_pin else '?'
        idx_type = idx_pin.get_type_signature() if idx_pin else '?'
        elem_str = f" Element:{span('bp-data-type', f'`{elem_type}`')}" if elem_pin else ""
        idx_str = f", Index:{span('bp-data-type', f'`{idx_type}`')}" if idx_pin else ""
        keyword = span("bp-keyword", "**For Each**")
        return f"{keyword} in ({array_val_raw}) [{elem_str}{idx_str} ]"

    def _format_timeline(self, node: K2Node_Timeline, visited_data_pins: Set[str]) -> str:
        timeline_name = node.timeline_name or "Unnamed Timeline"
        keyword = span("bp-keyword", "**Play Timeline**")
        timeline_name_span = span("bp-timeline-name", f"`{timeline_name}`")
        return f"{keyword} {timeline_name_span}"

    def _format_set_fields_in_struct(self, node: K2Node_SetFieldsInStruct, visited_data_pins: Set[str]) -> str:
        struct_pin = node.get_struct_pin()
        struct_str_raw = self.data_tracer.trace_pin_value(struct_pin, visited_pins=visited_data_pins.copy()) if struct_pin else span("bp-error", "<?>")
        exclude = {struct_pin.name.lower()} if struct_pin and struct_pin.name else set()
        fields_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins=exclude)
        keyword = span("bp-keyword", "**Set Fields**")
        return f"{keyword} in ({struct_str_raw}) {fields_str}"

    def _format_return_node(self, node: K2Node_FunctionResult, visited_data_pins: Set[str]) -> str:
        args_str = self._format_arguments(node, visited_data_pins.copy())
        keyword = span("bp-keyword", "**Return**")
        return f"{keyword}{args_str}"

    def _format_spawn_actor(self, node: K2Node_SpawnActorFromClass, visited_data_pins: Set[str]) -> str:
        class_pin = node.get_class_pin()
        class_name = self.data_tracer.trace_pin_value(class_pin, visited_pins=visited_data_pins.copy()) if class_pin else (f"`{extract_simple_name_from_path(node.spawn_class_path)}`" if node.spawn_class_path else "`UnknownClass`")
        spawn_transform_pin = node.get_spawn_transform_pin()
        spawn_transform_str = self.data_tracer.trace_pin_value(spawn_transform_pin, visited_pins=visited_data_pins.copy()) if spawn_transform_pin else "DefaultTransform"
        exclude = {'class', 'spawntransform'}
        other_args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins=exclude)
        keyword = span("bp-keyword", "**Spawn Actor**")
        class_name_span = span("bp-class-name", class_name) # class_name might already have spans
        return f"{keyword} {class_name_span} at ({spawn_transform_str}) {other_args_str}"

    def _format_add_component(self, node: K2Node_AddComponent, visited_data_pins: Set[str]) -> str:
        target_pin = node.get_target_pin()
        target_str_raw = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy()) if target_pin else span("bp-var", "`self`")
        component_class_pin = node.get_component_class_pin()
        comp_name = self.data_tracer.trace_pin_value(component_class_pin, visited_pins=visited_data_pins.copy()) if component_class_pin else (f"`{extract_simple_name_from_path(node.component_class_path)}`" if node.component_class_path else "`UnknownComponent`")
        target_fmt = self._format_target(target_str_raw)
        other_args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins={'componentclass', 'target'}) # Exclude target too
        keyword = span("bp-keyword", "**Add Component**")
        comp_name_span = span("bp-component-name", comp_name) # comp_name might already have spans
        return f"{keyword} {comp_name_span}{target_fmt} {other_args_str}"

    def _format_create_widget(self, node: K2Node_CreateWidget, visited_data_pins: Set[str]) -> str:
        widget_class_pin = node.get_widget_class_pin()
        widget_name = self.data_tracer.trace_pin_value(widget_class_pin, visited_pins=visited_data_pins.copy()) if widget_class_pin else (f"`{extract_simple_name_from_path(node.widget_class_path)}`" if node.widget_class_path else "`UnknownWidget`")
        owner_pin = node.get_owning_player_pin()
        owner_str = self.data_tracer.trace_pin_value(owner_pin, visited_pins=visited_data_pins.copy()) if owner_pin else "`DefaultPlayer`"
        other_args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins={'widgetclass', 'owningplayer'})
        keyword = span("bp-keyword", "**Create Widget**")
        widget_name_span = span("bp-widget-name", widget_name) # widget_name might already have spans
        return f"{keyword} {widget_name_span} for ({owner_str}) {other_args_str}"

    def _format_generic_create_object(self, node: K2Node_GenericCreateObject, visited_data_pins: Set[str]) -> str:
        class_pin = node.get_class_pin()
        class_name = self.data_tracer.trace_pin_value(class_pin, visited_pins=visited_data_pins.copy()) if class_pin else "`UnknownClass`"
        outer_pin = node.get_outer_pin()
        outer_str = self.data_tracer.trace_pin_value(outer_pin, visited_pins=visited_data_pins.copy()) if outer_pin else "`DefaultOuter`"
        other_args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins={'class', 'outer'})
        keyword = span("bp-keyword", "**Create Object**")
        class_name_span = span("bp-class-name", class_name) # class_name might already have spans
        return f"{keyword} {class_name_span} Outer=({outer_str}) {other_args_str}"

    # --- NEW: Format Call Array Function ---
    def _format_call_array_function(self, node: K2Node_CallArrayFunction, visited_data_pins: Set[str]) -> str:
        array_pin = node.get_target_pin()
        array_str_raw = self.data_tracer.trace_pin_value(array_pin, visited_pins=visited_data_pins.copy()) if array_pin else span("bp-error", "<?>")
        func_name = node.array_function_name or 'UnknownArrayFunction'
        exclude = {array_pin.name.lower()} if array_pin and array_pin.name else set()
        args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins=exclude)
        keyword = span("bp-keyword", "**Array Op**")
        func_name_span = span("bp-func-name", f"`{func_name}`")
        # Provide a slightly more descriptive format than just the trace result
        return f"{keyword} {func_name_span}{args_str} on ({array_str_raw})"

    def _format_format_text(self, node: K2Node_FormatText, visited_data_pins: Set[str]) -> str:
        format_pin = node.get_format_pin()
        format_string = self.data_tracer.trace_pin_value(format_pin, visited_pins=visited_data_pins.copy()) if format_pin else span("bp-error", "<?>")
        args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins={'format'})
        keyword = span("bp-keyword", "**Format Text**")
        return f"{keyword} {format_string} {args_str}"

    def _format_play_montage(self, node: K2Node_PlayMontage, visited_data_pins: Set[str]) -> str:
        target_pin = node.get_target_pin()
        target_str_raw = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy()) if target_pin else span("bp-var", "`self`")
        montage_pin = node.get_montage_to_play_pin()
        montage_str = self.data_tracer.trace_pin_value(montage_pin, visited_pins=visited_data_pins.copy()) if montage_pin else "`UnknownMontage`"
        target_fmt = self._format_target(target_str_raw)
        other_args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins={'target', 'montagetoplay'})
        keyword = span("bp-keyword", "**Play Montage**")
        montage_name_span = span("bp-montage-name", montage_str) # montage_str might already have spans
        return f"{keyword} {montage_name_span}{target_fmt} {other_args_str}"

    def _format_latent_action(self, node: K2Node_LatentAction, visited_data_pins: Set[str]) -> str:
        # Try to get a more specific name if available (e.g., from function name)
        action_name = getattr(node, 'function_name', None) or node.node_type
        args_str = self._format_arguments(node, visited_data_pins.copy())
        keyword = span("bp-keyword", "**Latent Action**")
        action_name_span = span("bp-action-name", f"`{action_name}`")
        return f"{keyword} {action_name_span}{args_str}"

    # --- NEW: Format Composite Node ---
    def _format_composite(self, node: K2Node_Composite, visited_data_pins: Set[str]) -> str:
        graph_name = node.bound_graph_name or "Unnamed Graph"
        keyword = span("bp-keyword", "**Collapsed Graph**")
        graph_name_span = span("bp-graph-name", f"`{graph_name}`") # Add new CSS class if desired
        # Don't typically show arguments for collapsed graphs in this view
        return f"{keyword}: {graph_name_span}"
    # --- END NEW ---

    def _format_generic(self, node: Node, visited_data_pins: Set[str]) -> str:
        args_str = self._format_arguments(node, visited_data_pins.copy())
        # Try to use Node Title if available and not just a generic type
        node_title = getattr(node, 'node_title', None)
        if node_title and node_title != node.node_type:
             # Use title if it's more descriptive than the type
             name_span = span("bp-node-title", f"`{node_title}`")
             keyword = span("bp-keyword", f"**{node.node_type.replace('K2Node_', '')}**") # Use simplified type as keyword
        else:
             name_span = span("bp-node-type", f"`{node.node_type}`")
             keyword = span("bp-keyword", "**Execute**") # Generic keyword

        return f"{keyword} {name_span}{args_str}"


# --- END OF FILE blueprint_parser/formatter/node_formatter.py ---