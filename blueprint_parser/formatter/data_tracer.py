# --- START OF FILE blueprint_parser/formatter/data_tracer.py ---

import re
from typing import Dict, Optional, Set, Any, List, TYPE_CHECKING, Tuple
import sys

# --- Use relative import ---
from ..nodes import (Node, Pin, K2Node_Knot, K2Node_VariableGet, K2Node_CallFunction,
                     K2Node_PromotableOperator, K2Node_CommutativeAssociativeBinaryOperator,
                     K2Node_EnhancedInputAction, K2Node_DynamicCast, K2Node_FlipFlop,
                     K2Node_Select, K2Node_MakeStruct, K2Node_BreakStruct,
                     K2Node_VariableSet, K2Node_Timeline, K2Node_InputAction, K2Node_InputAxisEvent,
                     K2Node_InputKey, K2Node_GetClassDefaults, K2Node_MakeArray, K2Node_MakeMap,
                     K2Node_GetArrayItem, K2Node_InputTouch, K2Node_InputAxisKeyEvent, K2Node_InputDebugKey,
                     K2Node_GenericCreateObject, K2Node_CreateWidget, K2Node_AddComponent,
                     K2Node_SpawnActorFromClass, K2Node_CreateDelegate, K2Node_CustomEvent, K2Node_Event,
                     K2Node_SetFieldsInStruct, K2Node_FormatText, K2Node_FunctionResult, K2Node_FunctionEntry,
                     K2Node_MacroInstance)
from ..utils import extract_simple_name_from_path, extract_member_name

if TYPE_CHECKING:
    from ..parser import BlueprintParser
    from .node_formatter import NodeFormatter

ENABLE_PARSER_DEBUG = False# Set to True for verbose tracing output
MAX_TRACE_DEPTH = 15

# --- Helper to wrap text in span ---
def span(css_class: str, text: str) -> str:
    return f'<span class="{css_class}">{text}</span>'

class DataTracer:
    def __init__(self, parser: 'BlueprintParser'):
        self.parser = parser
        self._node_formatter_instance = None
        self.resolved_pin_cache: Dict[str, str] = {}
        self.MATH_OPERATORS = {
            "Divide": "/", "Add": "+", "Subtract": "-", "Multiply": "*",
            "Less": "<", "Greater": ">", "LessEqual": "<=", "GreaterEqual": ">=",
            "EqualEqual": "==", "NotEqual": "!=",
            "BooleanAND": "AND", "BooleanOR": "OR", "BooleanXOR": "XOR", "BooleanNAND": "NAND",
            "Max": "MAX", "Min": "MIN", "FMax": "MAX", "FMin": "MIN",
            "Percent": "%"
        }
        self.TYPE_CONVERSIONS = {
            "Conv_BoolToFloat": "float", "Conv_BoolToInt": "int", "Conv_BoolToString": "string",
            "Conv_ByteToInt": "int", "Conv_ByteToFloat": "float",
            "Conv_IntToByte": "byte", "Conv_IntToFloat": "float", "Conv_IntToDouble": "double", "Conv_IntToString": "string", "Conv_IntToInt64": "int64",
            "Conv_Int64ToByte": "byte", "Conv_Int64ToInt": "int", "Conv_Int64ToString": "string",
            "Conv_FloatToBool": "bool", "Conv_FloatToInt": "int", "Conv_FloatToString": "string", "Conv_FloatToDouble": "double",
            "Conv_DoubleToBool": "bool", "Conv_DoubleToInt": "int", "Conv_DoubleToFloat": "float", "Conv_DoubleToString": "string",
            "Conv_StringToBool": "bool", "Conv_StringToInt": "int", "Conv_StringToFloat": "float", "Conv_StringToName": "name",
            "Conv_NameToBool": "bool", "Conv_NameToString": "string",
            "Conv_ObjectToString": "string",
        }

    @property
    def node_formatter(self) -> 'NodeFormatter':
        if self._node_formatter_instance is None:
            from .node_formatter import NodeFormatter
            self._node_formatter_instance = NodeFormatter(self.parser, self)
        return self._node_formatter_instance

    def clear_cache(self):
        if ENABLE_TRACER_DEBUG: print("DEBUG (DataTracer): Cache Cleared.", file=sys.stderr)
        self.resolved_pin_cache.clear()

    def trace_pin_value(self, pin_to_resolve: Optional[Pin], visited_pins: Optional[Set[str]] = None) -> str:
        """Main entry point. Traces a pin value starting from a Pin object."""
        if not pin_to_resolve: return span("bp-error", "[Missing Pin Object]")
        if not pin_to_resolve.id: return span("bp-error", "[Pin has no ID]")
        if visited_pins is None: visited_pins = set()
        # Add top-level debug print
        if ENABLE_TRACER_DEBUG: print(f"\n--- TRACE STARTING for Pin: {pin_to_resolve.name}({pin_to_resolve.id[:4]}) on Node {pin_to_resolve.node_guid[:8]} ---", file=sys.stderr)
        result = self._resolve_pin_value_recursive(pin_to_resolve, 0, visited_pins)
        if ENABLE_TRACER_DEBUG: print(f"--- TRACE FINISHED for Pin: {pin_to_resolve.name}({pin_to_resolve.id[:4]}) -> FINAL RESULT: '{result}' ---\n", file=sys.stderr)
        return result

    def _resolve_pin_value_recursive(self, pin_to_resolve: Pin, depth=0, visited_pins: Optional[Set[str]] = None) -> str:
        """Internal recursive function. Handles cycles and caches results."""
        if visited_pins is None: visited_pins = set()

        pin_id = pin_to_resolve.id
        node = self.parser.get_node_by_guid(pin_to_resolve.node_guid)
        node_name_for_debug = f"{node.name}({node.guid[:4]})" if node else f"Node({pin_to_resolve.node_guid[:4]})"
        pin_repr_for_debug = f"{pin_to_resolve.name}({pin_id[:4]}) on {node_name_for_debug}"
        indent = "  " * depth

        if ENABLE_TRACER_DEBUG: print(f"{indent}TRACE ENTER: Pin='{pin_repr_for_debug}', Depth={depth}, Cache Hit={pin_id in self.resolved_pin_cache}, In Path={pin_id in visited_pins}", file=sys.stderr)

        if pin_id in self.resolved_pin_cache:
            if ENABLE_TRACER_DEBUG: print(f"{indent}  TRACE CACHE HIT -> Returning cached '{self.resolved_pin_cache[pin_id]}'", file=sys.stderr)
            return self.resolved_pin_cache[pin_id]

        if depth > MAX_TRACE_DEPTH:
            if ENABLE_TRACER_DEBUG: print(f"{indent}  TRACE DEPTH LIMIT!", file=sys.stderr)
            return span("bp-error", "[Trace Depth Limit]")

        if pin_id in visited_pins:
            if ENABLE_TRACER_DEBUG: print(f"{indent}  TRACE CYCLE DETECTED!", file=sys.stderr)
            if node and isinstance(node, K2Node_VariableGet): return span("bp-var", f"`{node.variable_name}`")
            return span("bp-error", f"[Cycle->{pin_to_resolve.name or 'Pin'}]")

        visited_pins.add(pin_id)

        result = span("bp-error", "(Failed Trace)") # Default if logic fails

        try:
            # --- CORRECTED LOGIC ---
            # Find the source pin providing the value for 'pin_to_resolve'
            source_pin: Optional[Pin] = None
            if pin_to_resolve.is_input() and pin_to_resolve.linked_pins:
                # An input pin's value comes from the output pin it's linked to
                source_pin = pin_to_resolve.linked_pins[0] # Get the output pin that feeds this input
                if ENABLE_TRACER_DEBUG: print(f"{indent}  Input Pin: Found source via forward link: {source_pin.name}({source_pin.id[:4]}) on Node {source_pin.node_guid[:8]}", file=sys.stderr)
            elif pin_to_resolve.is_output():
                # An output pin's value comes from evaluating its own node
                source_pin = pin_to_resolve # The pin itself is the source in this context
                if ENABLE_TRACER_DEBUG: print(f"{indent}  Output Pin: Evaluating owning node.", file=sys.stderr)


            # If we found a source pin (either incoming link or the output pin itself)
            if source_pin:
                source_node = self.parser.get_node_by_guid(source_pin.node_guid)
                if not source_node:
                    result = span("bp-error", f"[Missing Source Node: {source_pin.node_guid[:8]}]")
                    if ENABLE_TRACER_DEBUG: print(f"{indent}  TRACE ERROR: Source node missing", file=sys.stderr)
                else:
                    # Evaluate the source node/pin that *provides* the value
                    # For inputs, depth increases. For outputs evaluated directly, depth stays same.
                    next_depth = depth + 1 if pin_to_resolve.is_input() else depth
                    result = self._trace_source_node(source_node, source_pin, next_depth, visited_pins.copy())
                    if ENABLE_TRACER_DEBUG: print(f"{indent}  TRACE RESULT (from source_node): Pin {pin_repr_for_debug} resolved as '{result[:100]}{'...' if len(result)>100 else ''}'", file=sys.stderr)
            else:
                # No source found (must be an unlinked input pin)
                result = self._format_default_value(pin_to_resolve)
                if ENABLE_TRACER_DEBUG: print(f"{indent}  TRACE BASE: Using Default Value: '{result}'", file=sys.stderr)

        except Exception as e:
            import traceback
            print(f"ERROR: Exception during trace for Pin {pin_repr_for_debug}: {e}", file=sys.stderr)
            if ENABLE_TRACER_DEBUG: traceback.print_exc()
            result = span("bp-error", "[Trace Error]")

        # Only remove from visited_pins if it was added in this call frame
        if pin_id in visited_pins:
            visited_pins.remove(pin_id)

        self.resolved_pin_cache[pin_id] = result
        if ENABLE_TRACER_DEBUG: print(f"{indent}TRACE EXIT : Pin='{pin_repr_for_debug}', Result='{result}', Caching.", file=sys.stderr)
        return result

    def _trace_source_node(self, source_node: Node, source_pin: Pin, depth: int, visited_pins: Set[str]) -> str:
        """Determines the value representation based on the source node type and the specific output pin."""
        indent = "  " * depth # For potential debug prints inside

        if isinstance(source_node, K2Node_Knot):
             input_knot_pin = source_node.get_passthrough_input_pin()
             return self._resolve_pin_value_recursive(input_knot_pin, depth, visited_pins) if input_knot_pin else span("bp-error", "[Knot Input Missing]")

        elif isinstance(source_node, K2Node_VariableGet):
            var_name = source_node.variable_name or "Var"
            return span("bp-var", f"`{var_name}`")

        elif isinstance(source_node, K2Node_VariableSet) and source_pin == source_node.get_value_output_pin():
            input_value_pin = source_node.get_value_input_pin()
            return self._resolve_pin_value_recursive(input_value_pin, depth + 1, visited_pins) if input_value_pin else span("bp-error", "[Set Input Missing]")

        elif isinstance(source_node, (K2Node_PromotableOperator, K2Node_CommutativeAssociativeBinaryOperator)):
             return self._format_operator(source_node, source_pin, depth, visited_pins)

        elif isinstance(source_node, K2Node_CallFunction) and source_node.is_pure_call:
             return self._format_pure_function_call(source_node, source_pin, depth, visited_pins)

        elif isinstance(source_node, K2Node_MacroInstance) and source_node.is_pure():
             return self._format_pure_macro_call(source_node, source_pin, depth, visited_pins)

        elif isinstance(source_node, K2Node_EnhancedInputAction):
            action_name = source_node.input_action_name or "InputAction"
            if source_pin == source_node.get_action_value_pin(): 
                return f"{span('bp-keyword', 'InputValue')}({span('bp-var', f'`{action_name}`')})"
            if source_pin == source_node.get_triggered_seconds_pin(): 
                return f"{span('bp-keyword', 'TriggeredTime')}({span('bp-var', f'`{action_name}`')})"
            if source_pin == source_node.get_elapsed_seconds_pin(): 
                return f"{span('bp-keyword', 'ElapsedTime')}({span('bp-var', f'`{action_name}`')})"
            return f"{span('bp-keyword', 'InputValue')}({span('bp-var', f'`{action_name}`')}.{span('bp-pin-name', f'`{source_pin.name}`')})"

        elif isinstance(source_node, K2Node_InputAction):
            action_name = source_node.action_name or "InputAction"
            if source_pin == source_node.get_key_pin(): 
                return f"{span('bp-keyword', 'InputKeyInfo')}({span('bp-var', f'`{action_name}`')})"
            else: 
                return f"{span('bp-keyword', 'InputEventValue')}({span('bp-var', f'`{action_name}`')}.{span('bp-pin-name', f'`{source_pin.name}`')})"

        elif isinstance(source_node, K2Node_InputAxisEvent):
            axis_name = source_node.axis_name or "InputAxis"
            if source_pin == source_node.get_axis_value_pin(): 
                return f"{span('bp-keyword', 'InputAxisValue')}({span('bp-var', f'`{axis_name}`')})"
            else: 
                return f"{span('bp-keyword', 'InputEventValue')}({span('bp-var', f'`{axis_name}`')}.{span('bp-pin-name', f'`{source_pin.name}`')})"

        elif isinstance(source_node, K2Node_InputKey):
            key_name = source_node.input_key_name or "InputKey"
            if source_pin == source_node.get_key_pin(): 
                return f"{span('bp-keyword', 'InputKeyInfo')}({span('bp-var', f'`{key_name}`')})"
            else: 
                return f"{span('bp-keyword', 'InputEventValue')}({span('bp-var', f'`{key_name}`')}.{span('bp-pin-name', f'`{source_pin.name}`')})"

        elif isinstance(source_node, K2Node_InputTouch):
            if source_pin == source_node.get_location_pin(): 
                return span("bp-keyword", "InputTouchLocation")
            if source_pin == source_node.get_finger_index_pin(): 
                return span("bp-keyword", "InputTouchIndex")
            return f"{span('bp-keyword', 'InputEventValue')}({span('bp-keyword', 'Touch')}.{span('bp-pin-name', f'`{source_pin.name}`')})"

        elif isinstance(source_node, K2Node_InputAxisKeyEvent):
            key_name = source_node.axis_key_name or "InputAxisKey"
            if source_pin == source_node.get_axis_value_pin(): 
                return f"{span('bp-keyword', 'InputAxisKeyValue')}({span('bp-var', f'`{key_name}`')})"
            else: 
                return f"{span('bp-keyword', 'InputEventValue')}({span('bp-var', f'`{key_name}`')}.{span('bp-pin-name', f'`{source_pin.name}`')})"

        elif isinstance(source_node, K2Node_InputDebugKey):
            key_name = source_node.input_key_name or "InputDebugKey"
            return f"{span('bp-keyword', 'InputDebugKeyInfo')}({span('bp-var', f'`{key_name}`')})"

        elif isinstance(source_node, K2Node_Timeline):
            timeline_name = source_node.timeline_name or 'Timeline'
            return f"{span('bp-var', f'`{timeline_name}`')}.{span('bp-pin-name', f'`{source_pin.name}`')}"

        elif isinstance(source_node, K2Node_DynamicCast):
            as_pin = source_node.get_as_pin()
            object_pin = source_node.get_object_pin()
            object_str = self._resolve_pin_value_recursive(object_pin, depth + 1, visited_pins) if object_pin else span("bp-error", "<?>")
            if source_pin == as_pin:
                cast_type = source_node.target_type or "UnknownType"
                return f"{span('bp-keyword', 'Cast')}<{span('bp-data-type', f'`{cast_type}`')}>({object_str})"
            elif source_pin.name == "Success": 
                return f"{span('bp-keyword', 'CastSucceeded')}({object_str})"
            else: 
                return f"{span('bp-keyword', 'Cast')}({object_str}).{span('bp-pin-name', f'`{source_pin.name}`')}"

        elif isinstance(source_node, K2Node_FlipFlop):
             if source_pin == source_node.get_is_a_pin(): 
                 return f"{span('bp-keyword', 'FlipFlop')}.{span('bp-pin-name', 'IsA')}"
             else: 
                 return f"{span('bp-keyword', 'FlipFlop')}.{span('bp-pin-name', f'`{source_pin.name}`')}"

        elif isinstance(source_node, K2Node_Select):
             index_pin = source_node.get_index_pin()
             index_str = self._resolve_pin_value_recursive(index_pin, depth + 1, visited_pins) if index_pin else span("bp-error", "<?>")
             options = source_node.get_option_pins()
             option_strs = [f"{span('bp-param-name', f'`{p.name}`')}={self._resolve_pin_value_recursive(p, depth + 1, visited_pins)}" for p in options if p.source_pin_for or not self._is_trivial_default(p)]
             return f"{span('bp-keyword', 'Select')}({span('bp-param-name', 'Index')}={index_str}, {span('bp-param-name', 'Options')}=[{', '.join(option_strs)}])"

        elif isinstance(source_node, K2Node_MakeStruct):
             struct_type = source_node.struct_type or "Struct"
             args = []
             for pin in source_node.get_input_pins(exclude_exec=True):
                 if pin.source_pin_for or not self._is_trivial_default(pin):
                     pin_val = self._resolve_pin_value_recursive(pin, depth + 1, visited_pins)
                     args.append(f"{span('bp-param-name', f'`{pin.name}`')}={pin_val}")
             args_str = ", ".join(args)
             return f"{span('bp-keyword', 'Make')}<{span('bp-data-type', f'`{struct_type}`')}>({args_str})"

        elif isinstance(source_node, K2Node_BreakStruct):
             input_pin = source_node.get_input_struct_pin()
             input_str = self._resolve_pin_value_recursive(input_pin, depth + 1, visited_pins) if input_pin else span("bp-error", "<?>")
             member_name = source_pin.name
             if re.match(r"^`[a-zA-Z0-9_]+`$", input_str):
                 return f"{input_str}.{span('bp-pin-name', f'`{member_name}`')}"
             else:
                 return f"({input_str}).{span('bp-pin-name', f'`{member_name}`')}"

        elif isinstance(source_node, K2Node_GetClassDefaults):
            class_name = extract_simple_name_from_path(source_node.target_class_path) or "UnknownClass"
            member_name = source_pin.name
            return f"{span('bp-var', f'`{class_name}`')}::{span('bp-keyword', 'Default')}.{span('bp-pin-name', f'`{member_name}`')}"

        elif isinstance(source_node, K2Node_MakeArray):
            item_pins = source_node.get_item_pins()
            item_strs = [self._resolve_pin_value_recursive(p, depth + 1, visited_pins) for p in item_pins]
            return f"{span('bp-literal-container', '[')}{', '.join(item_strs)}{span('bp-literal-container', ']')}"

        elif isinstance(source_node, K2Node_MakeMap):
            item_pairs = source_node.get_item_pins()
            pair_strs = [f"{self._resolve_pin_value_recursive(k, depth + 1, visited_pins)} {span('bp-operator', ':')} {self._resolve_pin_value_recursive(v, depth + 1, visited_pins)}" for k,v in item_pairs]
            return f"{span('bp-literal-container', '{')}{', '.join(pair_strs)}{span('bp-literal-container', '}')}"

        elif isinstance(source_node, K2Node_GetArrayItem):
            array_pin = source_node.get_target_pin()
            index_pin = source_node.get_index_pin()
            array_str = self._resolve_pin_value_recursive(array_pin, depth + 1, visited_pins) if array_pin else span("bp-error", "<?>")
            index_str = self._resolve_pin_value_recursive(index_pin, depth + 1, visited_pins) if index_pin else span("bp-error", "<?>")
            if re.match(r"^`[a-zA-Z0-9_]+`$", array_str):
                 return f"{array_str}{span('bp-operator', '[')}{index_str}{span('bp-operator', ']')}"
            else:
                 return f"({array_str}){span('bp-operator', '[')}{index_str}{span('bp-operator', ']')}"

        elif isinstance(source_node, (K2Node_CustomEvent, K2Node_Event, K2Node_FunctionEntry)) and source_pin.is_output():
             event_name = getattr(source_node, 'custom_function_name', None) or \
                          getattr(source_node, 'event_function_name', None) or \
                          extract_member_name(getattr(source_node,'FunctionReference', None)) or \
                          'Event'
             return f"{span('bp-event-name', f'`{event_name}`')}.{span('bp-param-name', f'`{source_pin.name}`')}"

        elif isinstance(source_node, K2Node_CreateDelegate):
            func_name_pin = source_node.get_function_name_pin()
            func_name_str = self._resolve_pin_value_recursive(func_name_pin, depth + 1, visited_pins) if func_name_pin else span("bp-var", f"`{source_node.raw_properties.get('FunctionName', '?')}`")
            obj_pin = source_node.get_object_pin()
            obj_str = self._resolve_pin_value_recursive(obj_pin, depth + 1, visited_pins) if obj_pin else span("bp-var", "`self`")
            return f"{span('bp-keyword', 'Delegate')}({func_name_str} {span('bp-keyword', 'on')} {obj_str})"

        elif source_node.ue_class == "/Script/BlueprintGraph.K2Node_Self":
            return span("bp-var", "`self`")

        elif source_node.ue_class == "/Script/BlueprintGraph.K2Node_Literal":
            output_pin = next((p for p in source_node.pins.values() if p.is_output()), None)
            if output_pin and output_pin.default_value is not None:
                return self._format_literal_value(output_pin, output_pin.default_value)
            else:
                return span("bp-error", "[Literal?]")

        else:
            # Fallback for impure/unhandled nodes producing this output pin
            formatter_desc, _ = self.node_formatter.format_node(source_node, "", set())
            if formatter_desc:
                 action_part = formatter_desc.split("-->")[-1].strip()
                 action_part = re.sub(r'\((.*)\)', '', action_part).strip() # Remove args ()
                 action_part = action_part.replace("**", "").replace("`", "")
                 pin_name_str = f".{span('bp-pin-name', f'`{source_pin.name}`')}" if source_pin.name and source_pin.name != "ReturnValue" else ""
                 return f"{span('bp-info', 'ResultOf')}({span('bp-generic-node', action_part)}){pin_name_str}"
            else:
                return f"{span('bp-info', 'ValueFrom')}({span('bp-node-type', f'`{source_node.node_type}`')}.{span('bp-pin-name', f'`{source_pin.name}`')})"

        return span("bp-error", f"[Unhandled Node Type: {source_node.node_type}]")

    # --- CORRECTED: Use _resolve_pin_value_recursive for internal calls ---
    def _format_operator(self, node: Node, output_pin: Pin, depth: int, visited_pins: Set[str]) -> str:
        """Formats promotable/commutative operators symbolically."""
        op_name = getattr(node, 'operation_name', 'Op')
        symbol = self.MATH_OPERATORS.get(op_name)
        inputs = node.get_input_pins(exclude_exec=True, include_hidden=False)
        inputs.sort(key=lambda p: p.name or "")
        # !!! Use _resolve_pin_value_recursive !!!
        input_vals = [self._resolve_pin_value_recursive(p, depth + 1, visited_pins) for p in inputs]

        if symbol and len(input_vals) == 2: 
            return f"({input_vals[0]} {span('bp-operator', symbol)} {input_vals[1]})"
        elif symbol and len(input_vals) == 1:
             if op_name == "BooleanNOT": 
                 return f"{span('bp-keyword', 'NOT')} ({input_vals[0]})"
        elif op_name in self.TYPE_CONVERSIONS and len(input_vals) == 1:
            target_type = self.TYPE_CONVERSIONS[op_name]
            return f"{span('bp-data-type', target_type)}({input_vals[0]})"
        elif op_name == "SelectFloat" and len(inputs) == 3:
             a_pin = node.get_pin("A")
             b_pin = node.get_pin("B")
             pick_a_pin = node.get_pin("Pick A") or node.get_pin("PickA")
             # !!! Use _resolve_pin_value_recursive !!!
             a_val = self._resolve_pin_value_recursive(a_pin, depth + 1, visited_pins) if a_pin else span("bp-error", "??")
             b_val = self._resolve_pin_value_recursive(b_pin, depth + 1, visited_pins) if b_pin else span("bp-error", "??")
             cond_val = self._resolve_pin_value_recursive(pick_a_pin, depth + 1, visited_pins) if pick_a_pin else span("bp-error", "???")
             return f"({cond_val} {span('bp-operator', '?')} {a_val} {span('bp-operator', ':')} {b_val})"
        elif op_name == "Concat_StrStr" and len(input_vals) >= 2: 
            return f" {span('bp-operator', '+')} ".join(input_vals)
        elif op_name == "Lerp" and len(inputs) == 3:
             # !!! Use _resolve_pin_value_recursive !!!
             args = {p.name: self._resolve_pin_value_recursive(p, depth + 1, visited_pins) for p in inputs}
             a_val = args.get("A", span("bp-error", "??"))
             b_val = args.get("B", span("bp-error", "??"))
             alpha_val = args.get("Alpha", span("bp-error", "??"))
             return f"{span('bp-func-name', 'Lerp')}({a_val}, {b_val}, {span('bp-param-name', 'Alpha')}={alpha_val})"
        elif op_name in ["FInterpTo", "VInterpTo", "RInterpTo"] and len(inputs) >= 4:
             # !!! Use _resolve_pin_value_recursive !!!
             args = {p.name: self._resolve_pin_value_recursive(p, depth + 1, visited_pins) for p in inputs}
             current = args.get("Current", span("bp-error", "??"))
             target_val = args.get("Target", span("bp-error", "??"))
             delta = args.get("DeltaTime", span("bp-error", "??"))
             speed = args.get("InterpSpeed", span("bp-error", "??"))
             return f"{span('bp-func-name', 'InterpTo')}({span('bp-param-name', 'Current')}={current}, {span('bp-param-name', 'Target')}={target_val}, {span('bp-param-name', 'DeltaTime')}={delta}, {span('bp-param-name', 'Speed')}={speed})"

        return f"{span('bp-func-name', op_name)}({', '.join(input_vals)})"

    # --- CORRECTED: Use _resolve_pin_value_recursive for internal calls ---
    def _format_pure_function_call(self, node: K2Node_CallFunction, output_pin: Pin, depth: int, visited_pins: Set[str]) -> str:
        """Formats pure K2Node_CallFunction symbolically."""
        func_name = node.function_name or 'PureFunc'
        target_pin = node.get_target_pin()
        # !!! Use _resolve_pin_value_recursive !!!
        target_str = self._resolve_pin_value_recursive(target_pin, depth + 1, visited_pins) if target_pin else span("bp-var", "`self`")

        args_list = []
        input_pins = [p for p in node.get_input_pins(exclude_exec=True, include_hidden=False) if p != target_pin]
        for pin in input_pins:
            # Check if pin is linked OR if its default value is non-trivial
            if pin.linked_pins or not self._is_trivial_default(pin): # Corrected check
                 # !!! Use _resolve_pin_value_recursive !!!
                 pin_val = self._resolve_pin_value_recursive(pin, depth + 1, visited_pins)
                 args_list.append(f"{span('bp-param-name', f'`{pin.name}`')}={pin_val}")
        args_str = ", ".join(args_list)

        is_static_call = target_str.startswith(span("bp-var", "`")) and target_str.endswith("</span>") and target_str != span("bp-var", "`self`") and '.' not in target_str

        call_prefix = ""
        # --- MODIFIED PREFIX LOGIC ---
        if target_str.startswith(span("bp-var", "`Default__")): # Check if target is a default library object
            call_prefix = "" # Hide the prefix for common library functions
        # --- END MODIFICATION ---
        elif target_str == span("bp-var", "`self`"):
             call_prefix = "" # Implicit self remains unchanged
        elif is_static_call:
             call_prefix = f"{target_str}." # Static calls remain unchanged
        else: # Object instance or complex expression target
            if any(c in target_str for c in ' +-/*%()[]{}='):
                 call_prefix = f"({target_str})." # Wrap complex targets
            else:
                 call_prefix = f"{target_str}." # Simple object target

        primary_output_pin = node.get_return_value_pin()
        if output_pin == primary_output_pin or not primary_output_pin:
            # Standard output: PrefixFunctionName(Args)
            return f"{call_prefix}{span('bp-func-name', f'`{func_name}`')}({args_str})"
        else:
            # Output is a secondary pin: (PrefixFunctionName(Args)).SecondaryPinName
            return f"({call_prefix}{span('bp-func-name', f'`{func_name}`')}({args_str})).{span('bp-pin-name', f'`{output_pin.name}`')}"
    # --- CORRECTED: Use _resolve_pin_value_recursive for internal calls ---
    def _format_pure_macro_call(self, node: K2Node_MacroInstance, output_pin: Pin, depth: int, visited_pins: Set[str]) -> str:
         """Formats pure K2Node_MacroInstance symbolically."""
         macro_name = node.macro_type or "PureMacro"
         args_list = []
         input_pins = node.get_input_pins(exclude_exec=True, include_hidden=False)
         for pin in input_pins:
             if pin.source_pin_for or not self._is_trivial_default(pin):
                  # !!! Use _resolve_pin_value_recursive !!!
                  pin_val = self._resolve_pin_value_recursive(pin, depth + 1, visited_pins)
                  args_list.append(f"{span('bp-param-name', f'`{pin.name}`')}={pin_val}")
         args_str = ", ".join(args_list)
         primary_output_pin = next((p for p in node.get_output_pins() if not p.is_execution()), None)
         base_call = f"{span('bp-func-name', f'`{macro_name}`')}({args_str})"
         if output_pin == primary_output_pin or not primary_output_pin: 
             return base_call
         else: 
             return f"({base_call}).{span('bp-pin-name', f'`{output_pin.name}`')}"

    # --- _format_default_value and _format_literal_value remain the same ---
    def _format_default_value(self, pin: Pin) -> str:
         val = pin.default_value; obj = pin.default_object; struct = pin.default_struct
         if val is not None: return self._format_literal_value(pin, val)
         if obj and obj.lower() != 'none': return self._format_literal_value(pin, obj)
         if struct: return self._format_literal_value(pin, str(struct))
         if pin.name and pin.name.lower() in ['self', 'target', 'worldcontextobject'] and pin.is_input(): 
             return span("bp-var", "`self`")
         # Return default literals wrapped in spans
         if pin.category == 'bool': 
             return span("bp-literal-bool", "false")
         if pin.category in ['byte', 'int', 'int64', 'real', 'float', 'double']: 
             return span("bp-literal-number", "0")
         if pin.category in ['string', 'text']: 
             return span("bp-literal-string", "''")
         if pin.category in ['name']: 
             return span("bp-literal-name", "`None`")
         if pin.category in ['object', 'class', 'interface', 'asset', 'assetclass']: 
             return span("bp-literal-object", "`None`")
         if pin.container_type in ['Array', 'Set', 'Map']: 
             return span("bp-literal-container", "[]" if pin.container_type == 'Array' else "{}")
         return span("bp-info", "(No Default)")

    def _format_literal_value(self, pin: Pin, val_str: str) -> str:
        category = pin.category; sub_category = pin.sub_category; sub_category_obj = pin.sub_category_object
        val_str = str(val_str).strip()
        if len(val_str) >= 2 and val_str.startswith('"') and val_str.endswith('"'): val_str = val_str[1:-1]
        elif len(val_str) >= 2 and val_str.startswith("'") and val_str.endswith("'"): val_str = val_str[1:-1]

        if category == 'bool': 
            return span("bp-literal-bool", val_str.lower())
        if category in ['byte', 'int', 'int64']:
            if sub_category_obj and ('Enum' in sub_category_obj or sub_category_obj.endswith('_UENUM')):
                enum_type = extract_simple_name_from_path(sub_category_obj) or "Enum"
                enum_val_str = val_str.split("::")[-1].split('.')[-1]
                return f"{span('bp-enum-type', f'`{enum_type}`')}::{span('bp-enum-value', f'`{enum_val_str}`')}"
            try: 
                return span("bp-literal-number", str(int(float(val_str))))
            except (ValueError, TypeError): 
                return span("bp-literal-unknown", val_str)
        if category in ['real', 'float', 'double']:
            try:
                num_val = float(val_str)
                if num_val.is_integer(): 
                    return span("bp-literal-number", str(int(num_val)))
                formatted = f"{num_val:.4f}".rstrip('0').rstrip('.')
                return span("bp-literal-number", formatted if formatted and formatted != '-' else '0.0')
            except (ValueError, TypeError): 
                return span("bp-literal-unknown", val_str)
        if category in ['string', 'text']: 
            return span("bp-literal-string", f"'{val_str.replace("'", "\\'")}'")
        if category == 'name': 
            return span("bp-literal-name", "`None`" if val_str.lower() == 'none' else f"`{val_str}`")
        if category == 'struct':
            struct_type_name = extract_simple_name_from_path(sub_category_obj) or 'Struct'
            if val_str.startswith('(') and val_str.endswith(')'):
                inner_val = val_str[1:-1]
                if re.match(r'X=[\d.-]+,Y=[\d.-]+,Z=[\d.-]+', inner_val, re.I): 
                    return f"{span('bp-struct-kw', 'Vector')}({span('bp-struct-val', inner_val)})"
                if re.match(r'X=[\d.-]+,Y=[\d.-]+$', inner_val, re.I): 
                    return f"{span('bp-struct-kw', 'Vector2D')}({span('bp-struct-val', inner_val)})"
                if re.match(r'(Pitch|P)=[\d.-]+,(Yaw|Y)=[\d.-]+,(Roll|R)=[\d.-]+', inner_val, re.I): 
                    return f"{span('bp-struct-kw', 'Rotator')}({span('bp-struct-val', inner_val)})"
                if re.match(r'R=[\d.-]+,G=[\d.-]+,B=[\d.-]+,A=[\d.-]+', inner_val, re.I): 
                    return f"{span('bp-struct-kw', 'Color')}({span('bp-struct-val', inner_val)})"
                tag_match = re.match(r'TagName="?([^"]*)"?', inner_val, re.I)
                if tag_match and struct_type_name == 'GameplayTag': 
                    return f"{span('bp-struct-kw', 'Tag')}({span('bp-struct-val', f'`{tag_match.group(1)}`')})"
                return f"{span('bp-keyword', 'Make')}<{span('bp-data-type', f'`{struct_type_name}`')}>({span('bp-struct-val', inner_val)})"
            return f"{span('bp-keyword', 'Make')}<{span('bp-data-type', f'`{struct_type_name}`')}>({span('bp-struct-val', val_str)})" if val_str else f"{span('bp-keyword', 'Make')}<{span('bp-data-type', f'`{struct_type_name}`')}>()"
        if category in ['object', 'interface', 'class', 'asset', 'assetclass', 'softclass', 'softobject']:
             obj_name = extract_simple_name_from_path(val_str)
             obj_name_str = f"`{obj_name}`" if obj_name and obj_name.lower() != 'none' else "`None`"
             return span("bp-literal-object", obj_name_str)

        return span("bp-literal-unknown", val_str)

    # --- _is_trivial_default remains the same ---
    def _is_trivial_default(self, pin: Pin) -> bool:
        # if pin.source_pin_for: return True # Original incorrect line
        if pin.linked_pins: return False # If the pin has connections, it's not using default values

        val = pin.default_value; obj = pin.default_object; struct = pin.default_struct; auto_val = pin.autogenerated_default_value
        val_str = str(val).lower().strip('"\'') if val is not None else ""
        obj_str = str(obj).lower().strip('"\'') if obj is not None else ""

        if val is not None and auto_val is not None and str(val).strip('"\'') == str(auto_val).strip('"\'') :
             if pin.category == 'name' and val_str == 'none': return True
             if pin.category == 'bool' and val_str == 'false': return True
             if pin.category not in ['name', 'bool']: return True

        if val is None and obj is None and struct is None: return True
        if val_str in ['0', '0.0', 'false', '', 'none', '()', 'null', 'nullptr'] and not obj_str and not struct: return True
        if obj_str in ['none', 'null', 'nullptr']: return True
        if pin.category == 'name' and val_str == 'none': return True

        if pin.category == 'struct':
            if val_str == '()': return True
            if val_str.startswith('(') and val_str.endswith(')'):
                inner = val_str[1:-1].replace(' ','').lower(); all_zero = True; parts = inner.split(',')
                for part in parts:
                    kv = part.split('=');
                    if len(kv) == 2:
                         try:
                             if float(kv[1]) != 0.0: all_zero = False; break
                         except ValueError: all_zero = False; break
                    else: all_zero = False; break
                if all_zero and parts: return True
            if isinstance(struct, dict) and not any(struct.values()): return True

        if pin.container_type in ["Array", "Set", "Map"] and val_str == "" and not obj and not struct: return True
        if pin.container_type == "Array" and val_str == "()": return True

        return False

    # --- CORRECTED: Use _resolve_pin_value_recursive ---
    def _trace_target_pin(self, target_pin: Optional[Pin], visited_pins: Set[str]) -> str:
        """Traces the target pin, returning `self`, `ClassName`, or a resolved value."""
        if not target_pin: 
            return span("bp-var", "`self`")
        # if not target_pin.source_pin_for: return "`self`" # Original incorrect line
        if not target_pin.linked_pins: 
            return span("bp-var", "`self`") # Check linked_pins instead

        # !!! Use _resolve_pin_value_recursive !!!
        target_value_str = self._resolve_pin_value_recursive(target_pin, depth=0, visited_pins=visited_pins.copy())

        if target_value_str == span("bp-var", "`self`"): 
            return span("bp-var", "`self`")
        match_class_default = re.match(r"^<span class=\"bp-var\">`([a-zA-Z0-9_]+)`</span>::Default", target_value_str)
        if match_class_default: 
            return span("bp-var", f"`{match_class_default.group(1)}`")
        return target_value_str


# --- END OF FILE blueprint_parser/formatter/data_tracer.py ---