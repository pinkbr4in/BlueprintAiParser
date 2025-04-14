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
                     K2Node_MacroInstance, K2Node_GetSubsystem) # Added K2Node_GetSubsystem
# --- Use relative import for utils ---
from ..utils import extract_simple_name_from_path, extract_member_name, parse_struct_default_value # Added parse_struct_default_value

if TYPE_CHECKING:
    from ..parser import BlueprintParser
    from .node_formatter import NodeFormatter

ENABLE_TRACER_DEBUG = False # Changed from ENABLE_PARSER_DEBUG to be specific
MAX_TRACE_DEPTH = 15

# --- Helper to wrap text in span ---
def span(css_class: str, text: str) -> str:
    """Consistently wrap text in a span with the given CSS class."""
    text = str(text) # Ensure text is string
    # Basic HTML escaping to prevent issues
    text = text.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
    return f'<span class="{css_class}">{text}</span>'

class DataTracer:
    def __init__(self, parser: 'BlueprintParser'):
        self.parser = parser
        self._node_formatter_instance = None
        self.resolved_pin_cache: Dict[str, str] = {}
        # --- (Keep MATH_OPERATORS and TYPE_CONVERSIONS) ---
        self.MATH_OPERATORS = {
            "Divide": "/", "Add": "+", "Subtract": "-", "Multiply": "*",
            "Less": "<", "Greater": ">", "LessEqual": "<=", "GreaterEqual": ">=",
            "EqualEqual": "==", "NotEqual": "!=",
            "BooleanAND": "AND", "BooleanOR": "OR", "BooleanXOR": "XOR", "BooleanNAND": "NAND",
            "Max": "MAX", "Min": "MIN", "FMax": "MAX", "FMin": "MIN",
            "Percent": "%", "BooleanNOT": "NOT" # Added NOT
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
            source_pin: Optional[Pin] = None
            if pin_to_resolve.is_input() and pin_to_resolve.linked_pins:
                source_pin = pin_to_resolve.linked_pins[0]
                if ENABLE_TRACER_DEBUG: print(f"{indent}  Input Pin: Found source via forward link: {source_pin.name}({source_pin.id[:4]}) on Node {source_pin.node_guid[:8]}", file=sys.stderr)
            elif pin_to_resolve.is_output():
                source_pin = pin_to_resolve
                if ENABLE_TRACER_DEBUG: print(f"{indent}  Output Pin: Evaluating owning node.", file=sys.stderr)

            if source_pin:
                source_node = self.parser.get_node_by_guid(source_pin.node_guid)
                if not source_node:
                    result = span("bp-error", f"[Missing Source Node: {source_pin.node_guid[:8]}]")
                    if ENABLE_TRACER_DEBUG: print(f"{indent}  TRACE ERROR: Source node missing", file=sys.stderr)
                else:
                    # Pass a copy of visited_pins down the chain
                    next_depth = depth + 1 if pin_to_resolve.is_input() else depth # Only increment depth when moving 'backward' to an input
                    result = self._trace_source_node(source_node, source_pin, next_depth, visited_pins.copy())
                    if ENABLE_TRACER_DEBUG: print(f"{indent}  TRACE RESULT (from source_node): Pin {pin_repr_for_debug} resolved as '{result[:100]}{'...' if len(result)>100 else ''}'", file=sys.stderr)
            else: # Pin has no source connection, use default value
                result = self._format_default_value(pin_to_resolve)
                if ENABLE_TRACER_DEBUG: print(f"{indent}  TRACE BASE: Using Default Value: '{result}'", file=sys.stderr)

        except Exception as e:
            import traceback
            print(f"ERROR: Exception during trace for Pin {pin_repr_for_debug}: {e}", file=sys.stderr)
            if ENABLE_TRACER_DEBUG: traceback.print_exc()
            result = span("bp-error", "[Trace Error]")

        # Remove from visited set only after returning from this level of recursion
        if pin_id in visited_pins: visited_pins.remove(pin_id)

        self.resolved_pin_cache[pin_id] = result
        if ENABLE_TRACER_DEBUG: print(f"{indent}TRACE EXIT : Pin='{pin_repr_for_debug}', Result='{result}', Caching.", file=sys.stderr)
        return result

    def _trace_source_node(self, source_node: Node, source_pin: Pin, depth: int, visited_pins: Set[str]) -> str:
        """Determines the value representation based on the source node type and the specific output pin."""
        indent = "  " * depth

        # --- Existing Fast Checks ---
        if isinstance(source_node, K2Node_Knot):
            input_knot_pin = source_node.get_passthrough_input_pin()
            return self._resolve_pin_value_recursive(input_knot_pin, depth, visited_pins.copy()) if input_knot_pin else span("bp-error", "[Knot Input Missing]") # Pass copy

        if isinstance(source_node, K2Node_VariableGet):
            var_name = source_node.variable_name or "Var"
            return span("bp-var", f"`{var_name}`")

        if isinstance(source_node, K2Node_VariableSet) and source_pin == source_node.get_value_output_pin():
            input_value_pin = source_node.get_value_input_pin()
            return self._resolve_pin_value_recursive(input_value_pin, depth + 1, visited_pins.copy()) if input_value_pin else span("bp-error", "[Set Input Missing]") # Pass copy

        # --- Specific Node Handling ---

        # --- UPDATED GetSubsystem ---
        elif isinstance(source_node, K2Node_GetSubsystem):
            if source_pin == source_node.get_return_value_pin():
                # --- Use helper method ---
                subsystem_name = source_node.get_subsystem_class_name() or "UnknownSubsystem"
                # --- END UPDATE ---
                target_str = ""
                if hasattr(source_node, 'get_player_controller_pin'):
                    pc_pin = source_node.get_player_controller_pin()
                    if pc_pin:
                        pc_str = self._resolve_pin_value_recursive(pc_pin, depth + 1, visited_pins.copy()) # Pass copy
                        target_str = f" from {pc_str}"
                return f"{span('bp-keyword', 'GetSubsystem')}({span('bp-class-name', f'`{subsystem_name}`')}){target_str}"
            else:
                 return f"{span('bp-info', 'ValueFrom')}({span('bp-node-type', source_node.node_type)}.{span('bp-pin-name', f'`{source_pin.name}`')})"
        # --- END GetSubsystem Update ---

        elif isinstance(source_node, K2Node_CreateWidget):
            if source_pin == source_node.get_return_value_pin():
                class_name = "`UnknownWidget`"
                class_pin = source_node.get_widget_class_pin()
                if class_pin:
                    if class_pin.linked_pins:
                        class_name = self._resolve_pin_value_recursive(class_pin, depth + 1, visited_pins.copy()) # Pass copy
                    else: # Use default object or node property (via helper)
                        resolved_name = source_node.get_widget_class_name()
                        class_name = f"`{resolved_name}`" if resolved_name else class_name
                return f"{span('bp-keyword', 'CreateWidget')}({span('bp-widget-name', class_name)})"

        elif isinstance(source_node, K2Node_SpawnActorFromClass):
            if source_pin == source_node.get_return_value_pin():
                class_name = "`UnknownActor`"
                class_pin = source_node.get_class_pin()
                if class_pin:
                    if class_pin.linked_pins:
                        class_name = self._resolve_pin_value_recursive(class_pin, depth + 1, visited_pins.copy()) # Pass copy
                    else: # Use default object or node property (via helper)
                        resolved_name = source_node.get_spawn_class_name()
                        class_name = f"`{resolved_name}`" if resolved_name else class_name
                return f"{span('bp-keyword', 'SpawnedActor')}({span('bp-class-name', class_name)})"

        elif isinstance(source_node, K2Node_AddComponent):
             if source_pin == source_node.get_return_value_pin():
                class_name = "`UnknownComponent`"
                class_pin = source_node.get_component_class_pin()
                if class_pin:
                    if class_pin.linked_pins:
                        class_name = self._resolve_pin_value_recursive(class_pin, depth + 1, visited_pins.copy()) # Pass copy
                    else: # Use default object or node property (via helper)
                        resolved_name = source_node.get_component_class_name()
                        class_name = f"`{resolved_name}`" if resolved_name else class_name
                return f"{span('bp-keyword', 'AddedComponent')}({span('bp-component-name', class_name)})"

        elif isinstance(source_node, K2Node_CallFunction) and source_node.function_name == "GetPlayerController":
             if source_pin == source_node.get_return_value_pin():
                  return span("bp-var", "`PlayerController`")

        elif isinstance(source_node, K2Node_GetClassDefaults):
            class_name = source_node.get_target_class_name() or "UnknownClass"
            member_name = source_pin.name or "UnknownMember"
            return f"{span('bp-var', f'`{class_name}`')}::{span('bp-keyword', 'Default')}.{span('bp-pin-name', f'`{member_name}`')}"

        elif isinstance(source_node, (K2Node_FunctionEntry, K2Node_Event, K2Node_CustomEvent,
                                      K2Node_EnhancedInputAction, K2Node_InputAction, K2Node_InputAxisEvent,
                                      K2Node_InputKey, K2Node_InputTouch, K2Node_InputAxisKeyEvent, K2Node_InputDebugKey)):
             # Handle output data pins from Events/Inputs/Function Entries
            if source_pin.is_output() and not source_pin.is_execution():
                 event_name = getattr(source_node, 'custom_function_name', None) or \
                              getattr(source_node, 'event_function_name', None) or \
                              getattr(source_node, 'input_action_name', None) or \
                              getattr(source_node, 'action_name', None) or \
                              getattr(source_node, 'axis_name', None) or \
                              getattr(source_node, 'input_key_name', None) or \
                              getattr(source_node, 'axis_key_name', None) or \
                              extract_member_name(getattr(source_node, 'FunctionReference', None)) or \
                              source_node.node_type # Fallback to node type
                 name_map = {"ReceiveBeginPlay": "BeginPlay", "ReceiveTick": "Tick"}
                 event_name = name_map.get(event_name, event_name)
                 return f"{span('bp-event-name', f'`{event_name}`')}.{span('bp-param-name', f'`{source_pin.name}`')}"

        elif isinstance(source_node, (K2Node_PromotableOperator, K2Node_CommutativeAssociativeBinaryOperator)):
              return self._format_operator(source_node, source_pin, depth, visited_pins.copy()) # Pass copy
        elif isinstance(source_node, K2Node_CallFunction) and source_node.is_pure_call:
              return self._format_pure_function_call(source_node, source_pin, depth, visited_pins.copy()) # Pass copy
        elif isinstance(source_node, K2Node_MacroInstance) and source_node.is_pure():
              return self._format_pure_macro_call(source_node, source_pin, depth, visited_pins.copy()) # Pass copy
        elif isinstance(source_node, K2Node_Timeline):
            timeline_name = source_node.timeline_name or 'Timeline'
            return f"{span('bp-var', f'`{timeline_name}`')}.{span('bp-pin-name', f'`{source_pin.name}`')}"
        elif isinstance(source_node, K2Node_DynamicCast):
            as_pin = source_node.get_as_pin()
            object_pin = source_node.get_object_pin()
            object_str = self._resolve_pin_value_recursive(object_pin, depth + 1, visited_pins.copy()) if object_pin else span("bp-error", "<?>") # Pass copy
            if source_pin == as_pin:
                cast_type = source_node.target_type or "UnknownType"
                return f"{span('bp-keyword', 'Cast')}<{span('bp-data-type', f'`{cast_type}`')}>({object_str})"
            elif source_pin.name == "Success": # Check specifically for the boolean output
                return f"{span('bp-keyword', 'CastSucceeded')}({object_str})"
            else:
                return f"{span('bp-keyword', 'Cast')}({object_str}).{span('bp-pin-name', f'`{source_pin.name}`')}"
        elif isinstance(source_node, K2Node_FlipFlop):
             if source_pin == source_node.get_is_a_pin():
                  return f"{span('bp-keyword', 'FlipFlop')}.{span('bp-pin-name', 'IsA')}"
             else:
                  return f"{span('bp-keyword', 'FlipFlop')}.{span('bp-pin-name', f'`{source_pin.name}`')}" # Should not happen often
        elif isinstance(source_node, K2Node_Select):
              index_pin = source_node.get_index_pin()
              index_str = self._resolve_pin_value_recursive(index_pin, depth + 1, visited_pins.copy()) if index_pin else span("bp-error", "<?>") # Pass copy
              options = source_node.get_option_pins()
              # Show only linked or non-trivial options for brevity
              option_strs = [f"{span('bp-param-name', f'`{p.name}`')}={self._resolve_pin_value_recursive(p, depth + 1, visited_pins.copy())}" for p in options if p.linked_pins or not self._is_trivial_default(p)] # Pass copy
              return f"{span('bp-keyword', 'Select')}({span('bp-param-name', 'Index')}={index_str}, {span('bp-param-name', 'Options')}=[{', '.join(option_strs)}])"

        # --- UPDATED MakeStruct ---
        elif isinstance(source_node, K2Node_MakeStruct):
            if source_pin == source_node.get_output_struct_pin():
                struct_type = source_node.struct_type or "Struct"
                args = []
                # Include hidden pins potentially, but filter trivial defaults
                # Use include_hidden=True to catch all struct members if needed, false otherwise
                for pin in source_node.get_input_pins(exclude_exec=True, include_hidden=True): # Adjust include_hidden as needed
                    if pin.linked_pins or not self._is_trivial_default(pin):
                        pin_val = self._resolve_pin_value_recursive(pin, depth + 1, visited_pins.copy()) # Pass copy
                        # Only add if value isn't considered empty/error after tracing
                        if pin_val and pin_val != span("bp-info", "(No Default)") and not pin_val.startswith('<span class="bp-error">'):
                             args.append(f"{span('bp-param-name', f'`{pin.name}`')}={pin_val}")
                args_str = ", ".join(args)
                return f"{span('bp-keyword', 'Make')}<{span('bp-data-type', f'`{struct_type}`')}>({args_str})"
            else:
                 return f"{span('bp-info', 'ValueFrom')}({span('bp-node-type', 'MakeStruct')}.{span('bp-pin-name', f'`{source_pin.name}`')})"
        # --- END MakeStruct Update ---

        elif isinstance(source_node, K2Node_BreakStruct):
              input_pin = source_node.get_input_struct_pin()
              input_str = self._resolve_pin_value_recursive(input_pin, depth + 1, visited_pins.copy()) if input_pin else span("bp-error", "<?>") # Pass copy
              member_name = source_pin.name or "UnknownMember"
              # Only use dot notation if the input is clearly a simple variable
              if re.match(r'^<span class="bp-var">`[a-zA-Z0-9_]+`</span>$', input_str):
                   return f"{input_str}.{span('bp-pin-name', f'`{member_name}`')}"
              else:
                   return f"({input_str}).{span('bp-pin-name', f'`{member_name}`')}"
        elif isinstance(source_node, K2Node_MakeArray):
            item_pins = source_node.get_item_pins()
            item_strs = [self._resolve_pin_value_recursive(p, depth + 1, visited_pins.copy()) for p in item_pins] # Pass copy
            return f"{span('bp-literal-container', '[')}{', '.join(item_strs)}{span('bp-literal-container', ']')}"
        elif isinstance(source_node, K2Node_MakeMap):
            item_pairs = source_node.get_item_pins()
            pair_strs = [f"{self._resolve_pin_value_recursive(k, depth + 1, visited_pins.copy())} {span('bp-operator', ':')} {self._resolve_pin_value_recursive(v, depth + 1, visited_pins.copy())}" for k,v in item_pairs] # Pass copy
            return f"{span('bp-literal-container', '{')}{', '.join(pair_strs)}{span('bp-literal-container', '}')}"
        elif isinstance(source_node, K2Node_GetArrayItem):
            array_pin = source_node.get_target_pin()
            index_pin = source_node.get_index_pin()
            array_str = self._resolve_pin_value_recursive(array_pin, depth + 1, visited_pins.copy()) if array_pin else span("bp-error", "<?>") # Pass copy
            index_str = self._resolve_pin_value_recursive(index_pin, depth + 1, visited_pins.copy()) if index_pin else span("bp-error", "<?>") # Pass copy
            if re.match(r'^<span class="bp-var">`[a-zA-Z0-9_]+`</span>$', array_str):
                 return f"{array_str}{span('bp-operator', '[')}{index_str}{span('bp-operator', ']')}"
            else:
                 return f"({array_str}){span('bp-operator', '[')}{index_str}{span('bp-operator', ']')}"
        elif isinstance(source_node, K2Node_CreateDelegate):
            func_name_pin = source_node.get_function_name_pin()
            # Pass copy when resolving pins
            func_name_str = self._resolve_pin_value_recursive(func_name_pin, depth + 1, visited_pins.copy()) if func_name_pin else span("bp-var", f"`{source_node.raw_properties.get('FunctionName', '?')}`")
            obj_pin = source_node.get_object_pin()
            obj_str = self._resolve_pin_value_recursive(obj_pin, depth + 1, visited_pins.copy()) if obj_pin else span("bp-var", "`self`")
            return f"{span('bp-keyword', 'Delegate')}({func_name_str} {span('bp-keyword', 'on')} {obj_str})"
        elif source_node.ue_class == "/Script/BlueprintGraph.K2Node_Self":
            return span("bp-var", "`self`")
        elif source_node.ue_class == "/Script/BlueprintGraph.K2Node_Literal":
            output_pin = next((p for p in source_node.pins.values() if p.is_output()), None)
            if output_pin and output_pin.default_value is not None:
                 return self._format_literal_value(output_pin, output_pin.default_value)
            else:
                 return span("bp-error", "[Literal?]")

        # --- Fallback for other unhandled nodes ---
        else:
            formatter_desc, _ = self.node_formatter.format_node(source_node, "", set()) # Use empty prefix/visited for description
            if formatter_desc:
                 action_part = formatter_desc.split("-->")[-1].strip() # Get part after arrow if exists
                 action_part = re.sub(r'\s*\(.*\)\s*$', '', action_part).strip() # Remove trailing args ()
                 action_part = action_part.replace("**", "").replace("`", "") # Clean up markdown
                 action_part = re.sub(r'<[^>]+>', '', action_part) # Strip remaining HTML spans
                 pin_name_str = f".{span('bp-pin-name', f'`{source_pin.name}`')}" if source_pin.name and source_pin.name != "ReturnValue" else ""
                 return f"{span('bp-info', 'ResultOf')}({span('bp-generic-node', action_part)}){pin_name_str}"
            else:
                 # Ultimate fallback if node formatting fails
                 return f"{span('bp-info', 'ValueFrom')}({span('bp-node-type', f'`{source_node.node_type}`')}.{span('bp-pin-name', f'`{source_pin.name}`')})"

        # This line should ideally not be reached if all cases are handled
        return span("bp-error", f"[Unhandled Node Type Fallback: {source_node.node_type}]") # Ensure fallback returns error

    def _format_operator(self, node: Node, output_pin: Pin, depth: int, visited_pins: Set[str]) -> str:
        op_name = getattr(node, 'operation_name', 'Op')
        symbol = self.MATH_OPERATORS.get(op_name)
        inputs = node.get_input_pins(exclude_exec=True, include_hidden=False)
        # Sort inputs deterministically, placing standard A,B,C first might be good
        inputs.sort(key=lambda p: (0 if p.name in ['A', 'B', 'C', 'D', 'E', 'Index'] else 1, p.name or ""))
        input_vals = [self._resolve_pin_value_recursive(p, depth + 1, visited_pins.copy()) for p in inputs] # Pass copy

        if symbol and len(input_vals) == 2:
            # Basic infix formatting
            return f"({input_vals[0]} {span('bp-operator', symbol)} {input_vals[1]})"
        elif symbol and len(input_vals) == 1:
             # Handle unary operators like NOT
             if op_name == "BooleanNOT":
                  return f"{span('bp-keyword', 'NOT')} ({input_vals[0]})"
             # Add other unary operators if needed
        elif op_name in self.TYPE_CONVERSIONS and len(input_vals) == 1:
            # Handle explicit type conversions
            target_type = self.TYPE_CONVERSIONS[op_name]
            return f"{span('bp-data-type', target_type)}({input_vals[0]})"
        elif op_name == "SelectFloat" and len(inputs) == 3: # Example specific handling
             a_pin = node.get_pin("A")
             b_pin = node.get_pin("B")
             pick_a_pin = node.get_pin("Pick A") or node.get_pin("PickA")
             # Pass copy when resolving
             a_val = self._resolve_pin_value_recursive(a_pin, depth + 1, visited_pins.copy()) if a_pin else span("bp-error", "??")
             b_val = self._resolve_pin_value_recursive(b_pin, depth + 1, visited_pins.copy()) if b_pin else span("bp-error", "??")
             cond_val = self._resolve_pin_value_recursive(pick_a_pin, depth + 1, visited_pins.copy()) if pick_a_pin else span("bp-error", "???")
             return f"({cond_val} {span('bp-operator', '?')} {a_val} {span('bp-operator', ':')} {b_val})"
        elif op_name == "Concat_StrStr" and len(input_vals) >= 2:
            return f" {span('bp-operator', '+')} ".join(input_vals)
        elif op_name == "Lerp" and len(inputs) == 3:
             args = {p.name: self._resolve_pin_value_recursive(p, depth + 1, visited_pins.copy()) for p in inputs} # Pass copy
             a_val = args.get("A", span("bp-error", "??"))
             b_val = args.get("B", span("bp-error", "??"))
             alpha_val = args.get("Alpha", span("bp-error", "??"))
             return f"{span('bp-func-name', 'Lerp')}({a_val}, {b_val}, {span('bp-param-name', 'Alpha')}={alpha_val})"
        elif op_name in ["FInterpTo", "VInterpTo", "RInterpTo"] and len(inputs) >= 4:
             args = {p.name: self._resolve_pin_value_recursive(p, depth + 1, visited_pins.copy()) for p in inputs} # Pass copy
             current = args.get("Current", span("bp-error", "??"))
             target_val = args.get("Target", span("bp-error", "??"))
             delta = args.get("DeltaTime", span("bp-error", "??"))
             speed = args.get("InterpSpeed", span("bp-error", "??"))
             return f"{span('bp-func-name', 'InterpTo')}({span('bp-param-name', 'Current')}={current}, {span('bp-param-name', 'Target')}={target_val}, {span('bp-param-name', 'DeltaTime')}={delta}, {span('bp-param-name', 'Speed')}={speed})"

        # Default fallback for other operators
        return f"{span('bp-func-name', op_name)}({', '.join(input_vals)})"

    def _format_pure_function_call(self, node: K2Node_CallFunction, output_pin: Pin, depth: int, visited_pins: Set[str]) -> str:
        """Formats pure K2Node_CallFunction symbolically."""
        func_name = node.function_name or 'PureFunc'
        target_pin = node.get_target_pin()

        # --- Specific Function Handling for MakeLiteralGameplayTagContainer ---
        if func_name == "MakeLiteralGameplayTagContainer":
            tag_container_pin = node.get_pin("Value") # Assuming the pin is named 'Value'
            tag_value_str = ""
            if tag_container_pin:
                if tag_container_pin.linked_pins:
                     tag_value_str = self._resolve_pin_value_recursive(tag_container_pin, depth + 1, visited_pins.copy()) # Pass copy
                elif not self._is_trivial_default(tag_container_pin):
                     tag_value_str = self._format_default_value(tag_container_pin)
                else:
                     tag_value_str = "Empty" # Explicitly state empty if default and trivial

            # Check common representations of empty/trivial
            if tag_value_str == "Empty" or \
               tag_value_str == '""' or tag_value_str == "''" or tag_value_str == "``" or \
               tag_value_str == span("bp-literal-tag", '``') or \
               tag_value_str.startswith(f"{span('bp-literal-struct-type', '`0`')} {span('bp-info','Tags')}") or \
               tag_value_str.startswith(f"{span('bp-literal-struct-type', '`GameplayTagContainer`')}({span('bp-literal-unknown', '...')})") or \
               tag_value_str.startswith(f"{span('bp-literal-struct-type', '`GameplayTagContainer`')}({span('bp-literal-struct-val', '()')})"):
                 return f"{span('bp-func-name', 'EmptyTagContainer')}()"
            else:
                 return f"{span('bp-func-name', 'MakeLiteralTagContainer')}({span('bp-param-name', 'Value')}={tag_value_str})"
        # --- END SPECIFIC ---

        # Pass copy when resolving target pin
        target_str_raw = self._resolve_pin_value_recursive(target_pin, depth + 1, visited_pins.copy()) if target_pin else span("bp-var", "`self`")

        args_list = []
        input_pins = [p for p in node.get_input_pins(exclude_exec=True, include_hidden=False) if p != target_pin]
        for pin in input_pins:
            if pin.linked_pins or not self._is_trivial_default(pin):
                 # Pass copy when resolving argument pins
                 pin_val = self._resolve_pin_value_recursive(pin, depth + 1, visited_pins.copy())
                 args_list.append(f"{span('bp-param-name', f'`{pin.name}`')}={pin_val}")
        args_str = ", ".join(args_list)

        is_static_call = False
        # --- ADDED None check ---
        if target_str_raw:
            match = re.match(r'^<span class="bp-(?:var|literal-object)">`([a-zA-Z0-9_]+)`</span>$', target_str_raw)
            if match and match.group(1) != 'self':
                is_static_call = True

        call_prefix = ""
        # --- ADDED None check ---
        if target_str_raw:
            if target_str_raw.startswith(span("bp-var", "`Default__")):
                call_prefix = "" # Hide default library prefix
            elif target_str_raw == span("bp-var", "`self`"):
                 call_prefix = "" # Implicit self
            elif is_static_call:
                 call_prefix = f"{target_str_raw}." # ClassName.
            else:
                 # Wrap complex targets
                 if any(sub in target_str_raw for sub in ['bp-operator', 'bp-func-name', 'bp-keyword', '?', '[', '{', '(']):
                     call_prefix = f"({target_str_raw})."
                 else:
                     call_prefix = f"{target_str_raw}."
        else: # Handle case where target trace failed
             call_prefix = f"({span('bp-error', '[Invalid Target]')})."
        # --- END ADDED None check ---

        func_name_span = span("bp-func-name", f"`{func_name}`")
        primary_output_pin = node.get_return_value_pin()
        base_call = f"{call_prefix}{func_name_span}({args_str})"

        if output_pin == primary_output_pin or not primary_output_pin:
            return base_call
        else:
            # If tracing a secondary output pin of a pure function
            return f"({base_call}).{span('bp-pin-name', f'`{output_pin.name}`')}"

    def _format_pure_macro_call(self, node: K2Node_MacroInstance, output_pin: Pin, depth: int, visited_pins: Set[str]) -> str:
        macro_name = node.macro_type or "PureMacro"
        args_list = []
        input_pins = node.get_input_pins(exclude_exec=True, include_hidden=False)
        for pin in input_pins:
            if pin.linked_pins or not self._is_trivial_default(pin):
                 # Pass copy when resolving pins
                 pin_val = self._resolve_pin_value_recursive(pin, depth + 1, visited_pins.copy())
                 args_list.append(f"{span('bp-param-name', f'`{pin.name}`')}={pin_val}")
        args_str = ", ".join(args_list)
        primary_output_pin = next((p for p in node.get_output_pins() if not p.is_execution()), None)
        base_call = f"{span('bp-func-name', f'`{macro_name}`')}({args_str})" # Use bp-func-name for macros too
        if output_pin == primary_output_pin or not primary_output_pin:
             return base_call
        else:
             return f"({base_call}).{span('bp-pin-name', f'`{output_pin.name}`')}"

    def _format_default_value(self, pin: Pin) -> str:
        val = pin.default_value; obj = pin.default_object; struct = pin.default_struct
        if val is not None: return self._format_literal_value(pin, val)
        if obj and obj.lower() != 'none':
             return self._format_literal_value(pin, obj)
        if struct is not None: return self._format_literal_value(pin, str(struct)) # Pass struct default string representation
        if pin.name and pin.name.lower() in ['self', 'target', 'worldcontextobject'] and pin.is_input():
             return span("bp-var", "`self`")
        # Return default literals wrapped in spans
        if pin.category == 'bool': return span("bp-literal-bool", "false")
        if pin.category in ['byte', 'int', 'int64', 'real', 'float', 'double']: return span("bp-literal-number", "0")
        if pin.category in ['string', 'text']: return span("bp-literal-string", "''")
        if pin.category in ['name']: return span("bp-literal-name", "`None`")
        if pin.category in ['object', 'class', 'interface', 'asset', 'assetclass', 'softobject', 'softclass']: return span("bp-literal-object", "`None`")
        if pin.container_type in ['Array', 'Set', 'Map']: return span("bp-literal-container", "[]" if pin.container_type == 'Array' else "{}")
        return span("bp-info", "(No Default)")

    # --- UPDATED Struct/Tag Handling ---
    def _format_literal_value(self, pin: Pin, val_str: str) -> str:
        """Formats literal values with proper escaping."""
        category = pin.category
        sub_category_obj = pin.sub_category_object

        val_str = str(val_str).strip()
        # Handle potential object path strings passed directly
        is_path = '/' in val_str or ':' in val_str or (val_str.startswith("'") and val_str.endswith("'") and len(val_str)>2)

        # Remove double quotes if they exist at start and end, unless it's clearly a path
        if len(val_str) >= 2 and not is_path:
            if val_str.startswith('"') and val_str.endswith('"'): val_str = val_str[1:-1]

        # Escape single quotes for display
        escaped_val_str = val_str.replace("'", r"\'") # Maybe only escape if not path?

        # --- Object/Class Handling ---
        if category in ['object', 'class', 'asset', 'assetclass', 'softobject', 'softclass', 'interface']:
             if is_path:
                 simple_name = extract_simple_name_from_path(val_str)
                 if simple_name: return span("bp-literal-object", f"`{simple_name}`")
                 else: # Fallback
                      if val_str.startswith("'") and val_str.endswith("'"): val_str = val_str[1:-1]
                      return span("bp-literal-object", f"`{val_str}`")
             elif val_str.lower() == 'none': return span("bp-literal-object", "`None`")
             else: return span("bp-literal-object", f"`{escaped_val_str}`")

        # --- Bool Handling ---
        if category == 'bool': return span("bp-literal-bool", escaped_val_str.lower())

        # --- Numeric/Enum Handling ---
        if category in ['byte', 'int', 'int64']:
            if sub_category_obj and ('Enum' in sub_category_obj or sub_category_obj.endswith('_UENUM')):
                enum_type = extract_simple_name_from_path(sub_category_obj) or "Enum"
                enum_val_str = escaped_val_str.split("::")[-1].split('.')[-1]
                return f"{span('bp-enum-type', f'`{enum_type}`')}::{span('bp-enum-value', f'`{enum_val_str}`')}"
            try: return span("bp-literal-number", str(int(float(escaped_val_str))))
            except (ValueError, TypeError): return span("bp-literal-unknown", escaped_val_str)
        if category in ['real', 'float', 'double']:
            try:
                num_val = float(escaped_val_str)
                if num_val.is_integer(): return span("bp-literal-number", str(int(num_val)))
                formatted = f"{num_val:.4f}".rstrip('0').rstrip('.')
                return span("bp-literal-number", formatted if formatted and formatted != '-' else '0.0')
            except (ValueError, TypeError): return span("bp-literal-unknown", escaped_val_str)

        # --- String/Name Handling ---
        if category in ['string', 'text']: return span("bp-literal-string", f"'{escaped_val_str}'") # Use single quotes visually
        if category == 'name': return span("bp-literal-name", "`None`" if escaped_val_str.lower() == 'none' else f"`{escaped_val_str}`")

        # --- UPDATED Struct/Tag Handling ---
        if category == 'struct':
            struct_name = extract_simple_name_from_path(sub_category_obj) if sub_category_obj else "Struct"
            # Use the utility function to parse simple defaults
            parsed_default = parse_struct_default_value(val_str)

            if parsed_default:
                # Specific logic for GameplayTag based on parsed content or type name
                is_gameplay_tag = (struct_name == "GameplayTag")

                if is_gameplay_tag and isinstance(parsed_default, str):
                    # Extract just the tag name if it's in the (TagName="...") format
                    tag_name = parsed_default
                    tag_match = re.match(r'\(?\s*TagName\s*=\s*"?`?([^"`]+)`?"?\s*\)?', tag_name, re.IGNORECASE)
                    if tag_match:
                        tag_name = tag_match.group(1)
                    # Handle cases where parse_struct_default_value might just return the tag name directly if simple enough
                    elif not tag_name.startswith('('):
                         pass # Assume it's already the tag name

                    if tag_name.lower() == 'none' or not tag_name or tag_name == '""':
                        return span("bp-literal-tag", '``') # Represent empty tag
                    else:
                        return span("bp-literal-tag", f'`{tag_name}`')

                # Special formatting for GameplayTagContainer (show count or ...)
                elif struct_name == "GameplayTagContainer" and isinstance(parsed_default, str):
                    tag_matches = re.findall(r'TagName\s*=\s*"?`?([^"`]+)`?"?', parsed_default, re.IGNORECASE)
                    valid_tags = [t for t in tag_matches if t.lower() != 'none' and t and t != '""']
                    if not valid_tags:
                        return f"{span('bp-literal-struct-type', '`0`')} {span('bp-info','Tags')}"
                    elif len(valid_tags) <= 3:
                        tags_str = ', '.join([span('bp-literal-tag', f'`{t}`') for t in valid_tags])
                        return f"{span('bp-literal-struct-type', '`{len(valid_tags)}`')} {span('bp-info','Tags')}({tags_str})"
                    else:
                         return f"{span('bp-literal-struct-type', '`{len(valid_tags)}`')} {span('bp-info','Tags')}({span('bp-literal-tag', f'`{valid_tags[0]}`')}, ...)"

                else: # General struct formatting
                     parsed_default_escaped = str(parsed_default).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                     return f"{span('bp-literal-struct-type', f'`{struct_name}`')}({span('bp-literal-struct-val', parsed_default_escaped)})"
            else: # Fallback for complex/unparsed structs
                 return f"{span('bp-literal-struct-type', f'`{struct_name}`')}({span('bp-literal-unknown', '...')})"
        # --- END Struct/Tag Handling Update ---

        return span("bp-literal-unknown", escaped_val_str) # Fallback

    def _is_trivial_default(self, pin: Pin) -> bool:
        if pin.linked_pins: return False # Linked pins are never using default

        val = pin.default_value; obj = pin.default_object; struct = pin.default_struct; auto_val = pin.autogenerated_default_value
        val_str = str(val).lower().strip('"\' ') if val is not None else "" # Strip spaces too
        obj_str = str(obj).lower().strip('"\' ') if obj is not None else ""

        # Check against autogenerated default first (can be efficient)
        if val is not None and auto_val is not None and str(val).strip('"\' ') == str(auto_val).strip('"\' ') :
             if pin.category == 'name' and val_str == 'none': return True
             if pin.category == 'bool' and val_str == 'false': return True
             # If default matches autogen for other simple types, consider it trivial
             if pin.category not in ['name', 'bool', 'struct', 'object', 'class', 'interface', 'asset', 'assetclass', 'softobject', 'softclass']:
                 try: # Check numeric zero
                    if float(val_str) == 0.0: return True
                 except: pass
                 if val_str == '': return True # Empty string
                 return True # Assume other matches are trivial

        # Standard checks
        if val is None and obj is None and struct is None: return True
        if obj_str in ['none', 'null', 'nullptr']: return True

        # Numeric/Bool/String checks
        if pin.category in ['byte', 'int', 'int64', 'real', 'float', 'double']:
            try:
                if float(val_str) == 0.0: return True
            except (ValueError, TypeError): pass
        if pin.category == 'bool' and val_str == 'false': return True
        if pin.category in ['string', 'text'] and val_str == '': return True
        if pin.category == 'name' and val_str == 'none': return True

        # Struct checks
        if pin.category == 'struct':
            raw_struct_val = str(val) if val is not None else (str(struct) if struct is not None else "")
            if raw_struct_val == '()' or raw_struct_val == '{}' or raw_struct_val == '': return True
            parsed_simple_default = parse_struct_default_value(raw_struct_val)
            if parsed_simple_default:
                if parsed_simple_default == "()": return True
                if isinstance(parsed_simple_default, str):
                    # Check for zero vector/rotator patterns more robustly
                    components = parsed_simple_default.strip('() ').split(',')
                    all_zero = True
                    for comp in components:
                        comp = comp.strip()
                        if not comp: continue
                        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*\s*=\s*(?:0(?:.0)?|false|""|``)$', comp, re.IGNORECASE):
                             # Check for empty tag name specifically
                            if not re.match(r'^TagName\s*=\s*(""|``|none)$', comp, re.IGNORECASE):
                                all_zero = False
                                break
                    if all_zero and components: return True

                # Check for empty GameplayTag via name or value
                struct_name = extract_simple_name_from_path(pin.sub_category_object) if pin.sub_category_object else ""
                if struct_name == "GameplayTag" and isinstance(parsed_simple_default, str):
                    if '(TagName="")' in parsed_simple_default.replace(" ","") or '(TagName=``)' in parsed_simple_default.replace(" ",""): return True
                # Check for empty GameplayTagContainer
                if struct_name == "GameplayTagContainer" and isinstance(parsed_simple_default, str):
                     if not re.search(r'TagName\s*=\s*"?`?[^"`None\s]+`?"?', parsed_simple_default, re.IGNORECASE): return True # No non-empty TagName found

        # Container checks
        if pin.container_type in ["Array", "Set", "Map"] and val_str in ['()', '']: return True

        return False

    def _trace_target_pin(self, target_pin: Optional[Pin], visited_pins: Set[str]) -> str:
        """Traces the target pin, returning `self`, `ClassName::Default`, `PlayerController`, or a resolved value."""
        if not target_pin: return span("bp-var", "`self`")
        if not target_pin.linked_pins: return span("bp-var", "`self`") # Default is self

        # --- Check the SOURCE of the value for the target pin ---
        source_pin = target_pin.linked_pins[0]
        source_node = self.parser.get_node_by_guid(source_pin.node_guid)

        if source_node:
            # Handle specific source nodes
            if isinstance(source_node, K2Node_GetClassDefaults):
                # Check if the source pin is one of the outputs (not 'self')
                if source_pin in source_node.get_output_pins():
                    class_name = source_node.get_target_class_name() or "UnknownClass"
                    return f"{span('bp-var', f'`{class_name}`')}::{span('bp-keyword', 'Default')}"
            elif isinstance(source_node, K2Node_CallFunction) and source_node.function_name == "GetPlayerController":
                if source_pin == source_node.get_return_value_pin():
                     return span("bp-var", "`PlayerController`")
            elif source_node.ue_class == "/Script/BlueprintGraph.K2Node_Self":
                 return span("bp-var", "`self`")
            # Add more special cases if needed (e.g., GetGameInstance?)

        # --- Fallback: Recursively trace the target pin normally ---
        target_value_str = self._resolve_pin_value_recursive(target_pin, depth=0, visited_pins=visited_pins.copy()) # Pass copy

        # Post-processing checks (keep existing)
        if target_value_str == span("bp-var", "`self`"): return span("bp-var", "`self`")
        if target_value_str == span("bp-var", "`PlayerController`"): return span("bp-var", "`PlayerController`")
        match_class_default = re.match(r'^(<span class="bp-var">`[a-zA-Z0-9_]+`</span>)::(<span class="bp-keyword">Default</span>)', target_value_str)
        if match_class_default: return target_value_str

        return target_value_str

# --- END OF FILE blueprint_parser/formatter/data_tracer.py ---