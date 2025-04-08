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
                     K2Node_FunctionEntry)
# --- Use relative import ---
from .data_tracer import DataTracer # Import DataTracer class
# --- Use relative import ---
from ..utils import extract_simple_name_from_path, extract_member_name

ENABLE_NODE_FORMATTER_DEBUG = False

class NodeFormatter:
    """Formats nodes into Markdown."""
    def __init__(self, parser, data_tracer: DataTracer): # Takes parser and data_tracer
        self.parser = parser
        self.data_tracer = data_tracer

    def _format_target(self, target_str: str) -> str:
        """Formats the target string for Markdown output."""
        if target_str == "`self`":
            return "" # Implicit self
        elif re.match(r"^`[a-zA-Z0-9_]+`$", target_str) and '.' not in target_str:
             return f" [on {target_str}]"
        else:
            return f" [on ({target_str})]"

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
                      pin_val = self.data_tracer.trace_pin_value(pin, visited_pins=visited_data_pins.copy())
                      args_list.append(f"`{pin.name}`={pin_val}")
             except Exception as e:
                 print(f"ERROR: Error tracing argument pin `{pin.name}` on node {node.guid}: {e}", file=sys.stderr)
                 # Print full traceback for argument tracing errors if debug enabled
                 if ENABLE_NODE_FORMATTER_DEBUG:
                      import traceback
                      traceback.print_exc()
                 args_list.append(f"`{pin.name}`=[Trace Error]")

         return f"({', '.join(args_list)})" if args_list else ""
    # ----------------------------------------------------


    def format_node(self, node: Node, prefix: str, visited_data_pins: Set[str]) -> Tuple[Optional[str], Optional[Pin]]:
        """Formats a node into Markdown, returns (description, primary_output_exec_pin)."""
        if node.is_pure():
            # if ENABLE_NODE_FORMATTER_DEBUG: print(f"DEBUG (NodeFormatter): Skipping pure node formatting: {node.name or node.guid} ({node.node_type})", file=sys.stderr)
            return None, None

        primary_exec_output = node.get_execution_output_pin()

        formatter_func = self._get_formatter_func(node)
        try:
            # Pass a copy of visited_data_pins to isolate data tracing for this node's arguments
            desc = formatter_func(node, visited_data_pins.copy())
        except Exception as e:
            import traceback
            print(f"ERROR formatting node {node.guid} ({node.node_type}): {e}", file=sys.stderr)
            if ENABLE_NODE_FORMATTER_DEBUG or ENABLE_PARSER_DEBUG: traceback.print_exc() # Use global debug flag potentially
            desc = f"**ERROR Formatting Node** `{node.node_type}`"

        return desc, primary_exec_output


    def _get_formatter_func(self, node: Node) -> callable:
        # ... (implementation is unchanged) ...
        if isinstance(node, (K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction, K2Node_InputAction, K2Node_InputAxisEvent, K2Node_InputKey, K2Node_InputTouch, K2Node_InputAxisKeyEvent, K2Node_InputDebugKey, K2Node_FunctionEntry)): return self._format_event
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
        if isinstance(node, K2Node_CallArrayFunction): return self._format_call_array_function
        if isinstance(node, K2Node_FormatText): return self._format_format_text
        if isinstance(node, K2Node_PlayMontage): return self._format_play_montage
        if isinstance(node, K2Node_LatentAction): return self._format_latent_action
        return self._format_generic


    # --- Specific Node Formatting Functions (Mostly unchanged, rely on _format_arguments) ---
    # ... (All _format_* methods remain the same as the previous corrected version) ...
    def _format_event(self, node: Node, visited_data_pins: Set[str]) -> str:
        name = "Unknown Event"; keyword = "**Event**"; args_list = []
        output_data_pins = node.get_output_pins(include_hidden=False)
        for pin in output_data_pins:
            if not pin.is_execution():
                pin_type_str = f":`{pin.get_type_signature()}`" if pin.get_type_signature() else ""
                args_list.append(f"`{pin.name}`{pin_type_str}")
        args_str = f" Args:({', '.join(args_list)})" if args_list else ""

        if isinstance(node, K2Node_CustomEvent): name = node.custom_function_name or "Unnamed Custom"; keyword = "**Custom Event**"
        elif isinstance(node, K2Node_EnhancedInputAction): name = node.input_action_name or "Unnamed Action"; keyword = "**Input Action**"
        elif isinstance(node, K2Node_InputAction): name = node.action_name or "Unnamed Legacy Action"; keyword = "**Input Action (Legacy)**"
        elif isinstance(node, K2Node_InputAxisEvent): name = node.axis_name or "Unnamed Axis"; keyword = "**Input Axis (Legacy)**"
        elif isinstance(node, K2Node_InputKey): name = node.input_key_name or "Unnamed Key"; keyword = "**Input Key (Legacy)**"
        elif isinstance(node, K2Node_InputTouch): name = "Touch"; keyword = "**Input Touch (Legacy)**"
        elif isinstance(node, K2Node_InputAxisKeyEvent): name = node.axis_key_name or "Unnamed Axis Key"; keyword = "**Input Axis Key (Legacy)**"
        elif isinstance(node, K2Node_InputDebugKey): name = node.input_key_name or "Unnamed Debug Key"; keyword = "**Input Debug Key (Legacy)**"
        elif isinstance(node, K2Node_FunctionEntry):
             func_ref = node.raw_properties.get("FunctionReference"); name = extract_member_name(func_ref) or "Unnamed Function Entry"; keyword = "**Function Entry**"
        elif isinstance(node, K2Node_Event):
            name = node.event_function_name or "Unnamed Event"; name_map = {"ReceiveBeginPlay": "Begin Play", "ReceiveTick": "Tick", "ReceiveAnyDamage": "Any Damage", "ReceiveEndPlay": "End Play", "ReceiveDestroyed": "Destroyed", "OnComponentBeginOverlap": "Component Begin Overlap", "OnComponentEndOverlap": "Component End Overlap", "OnActorBeginOverlap": "Actor Begin Overlap", "OnActorEndOverlap": "Actor End Overlap", "OnTakeAnyDamage": "Take Any Damage", "ReceiveDrawHUD": "Draw HUD"}; name = name_map.get(name, name); keyword = "**Event**"
        return f"{keyword} `{name}`{args_str}"

    def _format_variable_set(self, node: K2Node_VariableSet, visited_data_pins: Set[str]) -> str:
        var_name = node.variable_name or "UnknownVar"; value_pin = node.get_value_input_pin(); target_pin = node.get_target_pin()
        target_str = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy())
        value_str = self.data_tracer.trace_pin_value(value_pin, visited_pins=visited_data_pins.copy()) if value_pin else "<?>" # Pass Pin object
        var_type_sig = node.variable_type or (value_pin.get_type_signature() if value_pin else None); var_type = f":`{var_type_sig}`" if var_type_sig else ""
        target_fmt = self._format_target(target_str)
        return f"**Set** `{var_name}`{var_type} = {value_str}{target_fmt}"

    def _format_call_function(self, node: K2Node_CallFunction, visited_data_pins: Set[str]) -> str:
        func_name = node.function_name or 'UnknownFunction'; target_pin = node.get_target_pin()
        target_str = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy())
        args_str = self._format_arguments(node, visited_data_pins.copy())
        latent_info = " [(Latent)]" if node.is_latent else ""; dev_only = " [(Dev Only)]" if getattr(node, 'is_dev_only', False) else ""
        return_pin = next((p for p in node.get_output_pins() if not p.is_execution() and p.name == "ReturnValue"), None)
        return_type = f" -> `{return_pin.get_type_signature()}`" if return_pin else ""
        is_static_call = target_str.startswith("`") and target_str.endswith("`") and target_str != "`self`" and '.' not in target_str
        if is_static_call: return f"**Static Call** {target_str}.`{func_name}`{args_str}{return_type}{latent_info}{dev_only}"
        else: target_fmt = self._format_target(target_str); return f"**Call** `{func_name}`{args_str}{target_fmt}{return_type}{latent_info}{dev_only}"

    def _format_call_parent_function(self, node: K2Node_CallParentFunction, visited_data_pins: Set[str]) -> str:
        func_name = node.parent_function_name or (node.function_name or 'UnknownFunction'); args_str = self._format_arguments(node, visited_data_pins.copy())
        return f"**Call Parent** `{func_name}`{args_str}"

    def _format_macro_instance(self, node: K2Node_MacroInstance, visited_data_pins: Set[str]) -> str:
        macro_name = node.macro_type or "Unknown Macro"
        if node.macro_type == "FlipFlop": return f"**FlipFlop**"
        if node.macro_type == "Gate": is_open_pin = node.get_pin(pin_name="IsOpen"); is_open_val = self.data_tracer.trace_pin_value(is_open_pin, visited_pins=visited_data_pins.copy()) if is_open_pin else "<?>"; return f"**Gate** (IsOpen={is_open_val})"
        if node.macro_type == "IsValid": input_pin = node.get_pin(pin_name="Input Object") or node.get_pin(pin_name="inObject") or node.get_pin(pin_name="In"); input_val = self.data_tracer.trace_pin_value(input_pin, visited_pins=visited_data_pins.copy()) if input_pin else "<?>"; return f"**IsValid** ({input_val})"
        if node.macro_type in ("ForEachLoop", "ForEachLoopWithBreak"): array_pin = node.get_pin(pin_name="Array"); array_val = self.data_tracer.trace_pin_value(array_pin, visited_pins=visited_data_pins.copy()) if array_pin else "<?>"; elem_pin = node.get_pin("Array Element"); idx_pin = node.get_pin("Array Index"); elem_str = f" Element:`{elem_pin.get_type_signature()}`" if elem_pin else ""; idx_str = f", Index:`{idx_pin.get_type_signature()}`" if idx_pin else ""; return f"**For Each** in ({array_val}) [{elem_str}{idx_str} ]"
        if node.macro_type in ("ForLoop", "ForLoopWithBreak"): first_idx_pin = node.get_pin(pin_name="First Index") or node.get_pin(pin_name="FirstIndex"); last_idx_pin = node.get_pin(pin_name="Last Index") or node.get_pin(pin_name="LastIndex"); first_val = self.data_tracer.trace_pin_value(first_idx_pin, visited_pins=visited_data_pins.copy()) if first_idx_pin else "<?>"; last_val = self.data_tracer.trace_pin_value(last_idx_pin, visited_pins=visited_data_pins.copy()) if last_idx_pin else "<?>"; return f"**For Loop** (Index from {first_val} to {last_val})"
        if node.macro_type == "WhileLoop": cond_pin = node.get_pin(pin_name="Condition"); cond_val = self.data_tracer.trace_pin_value(cond_pin, visited_pins=visited_data_pins.copy()) if cond_pin else "<?>"; return f"**While Loop** (Condition={cond_val})"
        if node.macro_type == "DoN": n_pin = node.get_pin(pin_name="N"); n_val = self.data_tracer.trace_pin_value(n_pin, visited_pins=visited_data_pins.copy()) if n_pin else "<?>"; return f"**Do N Times** (N={n_val})"
        if node.macro_type == "DoOnce": return f"**Do Once**"
        if node.macro_type == "MultiGate": return f"**MultiGate**"
        args_str = self._format_arguments(node, visited_data_pins.copy()); return f"**Macro** `{macro_name}`{args_str}"

    def _format_if(self, node: K2Node_IfThenElse, visited_data_pins: Set[str]) -> str:
        condition_pin = node.get_condition_pin(); condition_str = self.data_tracer.trace_pin_value(condition_pin, visited_pins=visited_data_pins.copy()) if condition_pin else "<?>"
        return f"**If** ({condition_str})"

    def _format_sequence(self, node: K2Node_ExecutionSequence, visited_data_pins: Set[str]) -> str: return f"**Sequence**"
    def _format_flipflop(self, node: K2Node_FlipFlop, visited_data_pins: Set[str]) -> str: return f"**FlipFlop**"

    def _format_dynamic_cast(self, node: K2Node_DynamicCast, visited_data_pins: Set[str]) -> str:
        object_pin = node.get_object_pin(); object_str = self.data_tracer.trace_pin_value(object_pin, visited_pins=visited_data_pins.copy()) if object_pin else "<?>"
        cast_type = f"`{node.target_type}`" if node.target_type else "`UnknownType`"; as_pin = node.get_as_pin(); as_pin_str = f" (as `{as_pin.name}`)" if as_pin else ""
        return f"**Cast** ({object_str}) To {cast_type}{as_pin_str}"

    def _format_delegate_binding(self, node: Node, visited_data_pins: Set[str], action: str) -> str:
        delegate_prop_name = node.delegate_name or "?Delegate?"; target_pin = node.get_target_pin(); delegate_input_pin = node.get_delegate_pin()
        target_str = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy()) if target_pin else "`self`"
        event_str = self.data_tracer.trace_pin_value(delegate_input_pin, visited_pins=visited_data_pins.copy()) if delegate_input_pin else "*(Unlinked Delegate Input)*"
        target_fmt = self._format_target(target_str)
        return f"**{action}** Delegate `{delegate_prop_name}` to {event_str}{target_fmt}"

    def _format_add_delegate(self, node: K2Node_AddDelegate, visited_data_pins: Set[str]) -> str: return self._format_delegate_binding(node, visited_data_pins, "Bind")
    def _format_assign_delegate(self, node: K2Node_AssignDelegate, visited_data_pins: Set[str]) -> str: return self._format_delegate_binding(node, visited_data_pins, "Assign")
    def _format_remove_delegate(self, node: K2Node_RemoveDelegate, visited_data_pins: Set[str]) -> str: return self._format_delegate_binding(node, visited_data_pins, "Unbind")
    def _format_clear_delegate(self, node: K2Node_ClearDelegate, visited_data_pins: Set[str]) -> str:
        delegate_prop_name = node.delegate_name or "?Delegate?"; target_pin = node.get_target_pin(); target_str = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy()) if target_pin else "`self`"
        target_fmt = self._format_target(target_str); return f"**Unbind All** from Delegate `{delegate_prop_name}`{target_fmt}"

    def _format_call_delegate(self, node: K2Node_CallDelegate, visited_data_pins: Set[str]) -> str:
        delegate_name = node.delegate_name or 'UnknownDelegate'; target_pin = node.get_target_pin(); target_str = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy()) if target_pin else "`self`"
        args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins={'delegate'}); target_fmt = self._format_target(target_str)
        return f"**Call Delegate** `{delegate_name}`{args_str}{target_fmt}"

    def _format_switch(self, node: K2Node_Switch, visited_data_pins: Set[str]) -> str:
        selection_pin = node.get_selection_pin(); selection_str = self.data_tracer.trace_pin_value(selection_pin, visited_pins=visited_data_pins.copy()) if selection_pin else "<?>"
        switch_type = "";
        if isinstance(node, K2Node_SwitchEnum): switch_type = f" on Enum `{node.enum_type}`" if node.enum_type else " on Enum"
        elif selection_pin and selection_pin.category != 'exec': switch_type = f" on `{selection_pin.get_type_signature()}`"
        return f"**Switch** ({selection_str}){switch_type}"

    def _format_foreach_loop(self, node: K2Node_ForEachLoop, visited_data_pins: Set[str]) -> str:
        array_pin = node.get_array_pin(); array_val = self.data_tracer.trace_pin_value(array_pin, visited_pins=visited_data_pins.copy()) if array_pin else "<?>"
        elem_pin = node.get_array_element_pin(); idx_pin = node.get_array_index_pin(); elem_str = f" Element:`{elem_pin.get_type_signature()}`" if elem_pin else ""; idx_str = f", Index:`{idx_pin.get_type_signature()}`" if idx_pin else ""
        return f"**For Each** in ({array_val}) [{elem_str}{idx_str} ]"

    def _format_timeline(self, node: K2Node_Timeline, visited_data_pins: Set[str]) -> str:
        timeline_name = node.timeline_name or "Unnamed Timeline"; return f"**Play Timeline** `{timeline_name}`"

    def _format_set_fields_in_struct(self, node: K2Node_SetFieldsInStruct, visited_data_pins: Set[str]) -> str:
        struct_pin = node.get_struct_pin(); struct_str = self.data_tracer.trace_pin_value(struct_pin, visited_pins=visited_data_pins.copy()) if struct_pin else "<?>"
        exclude = {struct_pin.name.lower()} if struct_pin and struct_pin.name else set(); fields_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins=exclude)
        return f"**Set Fields** in ({struct_str}) {fields_str}"

    def _format_return_node(self, node: K2Node_FunctionResult, visited_data_pins: Set[str]) -> str:
        args_str = self._format_arguments(node, visited_data_pins.copy()); return f"**Return**{args_str}"

    def _format_spawn_actor(self, node: K2Node_SpawnActorFromClass, visited_data_pins: Set[str]) -> str:
        class_pin = node.get_class_pin(); class_name = self.data_tracer.trace_pin_value(class_pin, visited_pins=visited_data_pins.copy()) if class_pin else (f"`{extract_simple_name_from_path(node.spawn_class_path)}`" if node.spawn_class_path else "`UnknownClass`")
        spawn_transform_pin = node.get_spawn_transform_pin(); spawn_transform_str = self.data_tracer.trace_pin_value(spawn_transform_pin, visited_pins=visited_data_pins.copy()) if spawn_transform_pin else "DefaultTransform"
        exclude = {'class', 'spawntransform'}; other_args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins=exclude)
        return f"**Spawn Actor** {class_name} at ({spawn_transform_str}) {other_args_str}"

    def _format_add_component(self, node: K2Node_AddComponent, visited_data_pins: Set[str]) -> str:
        target_pin = node.get_target_pin(); target_str = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy()) if target_pin else "`self`"
        component_class_pin = node.get_component_class_pin(); comp_name = self.data_tracer.trace_pin_value(component_class_pin, visited_pins=visited_data_pins.copy()) if component_class_pin else (f"`{extract_simple_name_from_path(node.component_class_path)}`" if node.component_class_path else "`UnknownComponent`")
        target_fmt = self._format_target(target_str); other_args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins={'componentclass', 'target'}) # Exclude target too
        return f"**Add Component** {comp_name}{target_fmt} {other_args_str}"

    def _format_create_widget(self, node: K2Node_CreateWidget, visited_data_pins: Set[str]) -> str:
        widget_class_pin = node.get_widget_class_pin(); widget_name = self.data_tracer.trace_pin_value(widget_class_pin, visited_pins=visited_data_pins.copy()) if widget_class_pin else (f"`{extract_simple_name_from_path(node.widget_class_path)}`" if node.widget_class_path else "`UnknownWidget`")
        owner_pin = node.get_owning_player_pin(); owner_str = self.data_tracer.trace_pin_value(owner_pin, visited_pins=visited_data_pins.copy()) if owner_pin else "`DefaultPlayer`"
        other_args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins={'widgetclass', 'owningplayer'})
        return f"**Create Widget** {widget_name} for ({owner_str}) {other_args_str}"

    def _format_generic_create_object(self, node: K2Node_GenericCreateObject, visited_data_pins: Set[str]) -> str:
        class_pin = node.get_class_pin(); class_name = self.data_tracer.trace_pin_value(class_pin, visited_pins=visited_data_pins.copy()) if class_pin else "`UnknownClass`"
        outer_pin = node.get_outer_pin(); outer_str = self.data_tracer.trace_pin_value(outer_pin, visited_pins=visited_data_pins.copy()) if outer_pin else "`DefaultOuter`"
        other_args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins={'class', 'outer'})
        return f"**Create Object** {class_name} Outer=({outer_str}) {other_args_str}"

    def _format_call_array_function(self, node: K2Node_CallArrayFunction, visited_data_pins: Set[str]) -> str:
        array_pin = node.get_target_pin(); array_str = self.data_tracer.trace_pin_value(array_pin, visited_pins=visited_data_pins.copy()) if array_pin else "<?>"
        func_name = node.array_function_name or 'UnknownArrayFunction'; exclude = {array_pin.name.lower()} if array_pin and array_pin.name else set()
        args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins=exclude)
        return f"**Array Op** `{func_name}`{args_str} on ({array_str})"

    def _format_format_text(self, node: K2Node_FormatText, visited_data_pins: Set[str]) -> str:
        format_pin = node.get_format_pin(); format_string = self.data_tracer.trace_pin_value(format_pin, visited_pins=visited_data_pins.copy()) if format_pin else "<?>"
        args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins={'format'})
        return f"**Format Text** {format_string} {args_str}"

    def _format_play_montage(self, node: K2Node_PlayMontage, visited_data_pins: Set[str]) -> str:
        target_pin = node.get_target_pin(); target_str = self.data_tracer._trace_target_pin(target_pin, visited_data_pins.copy()) if target_pin else "`self`"
        montage_pin = node.get_montage_to_play_pin(); montage_str = self.data_tracer.trace_pin_value(montage_pin, visited_pins=visited_data_pins.copy()) if montage_pin else "`UnknownMontage`"
        target_fmt = self._format_target(target_str); other_args_str = self._format_arguments(node, visited_data_pins.copy(), exclude_pins={'target', 'montagetoplay'})
        return f"**Play Montage** {montage_str}{target_fmt} {other_args_str}"

    def _format_latent_action(self, node: K2Node_LatentAction, visited_data_pins: Set[str]) -> str:
        action_name = node.node_type; args_str = self._format_arguments(node, visited_data_pins.copy())
        return f"**Latent Action** `{action_name}`{args_str}"

    def _format_generic(self, node: Node, visited_data_pins: Set[str]) -> str:
        args_str = self._format_arguments(node, visited_data_pins.copy()); return f"**Execute** `{node.node_type}`{args_str}"


# --- END OF FILE blueprint_parser/formatter/node_formatter.py ---