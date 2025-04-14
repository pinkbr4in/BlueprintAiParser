# --- START OF FILE blueprint_parser/formatter/data_tracer.py ---

import re
from typing import Dict, Optional, Set, Any, List, TYPE_CHECKING, Tuple
import sys

# --- Use relative import ---
# Add missing imports based on the request
from ..nodes import (Node, Pin, K2Node_Knot, K2Node_VariableGet, K2Node_CallFunction,
                     K2Node_PromotableOperator, K2Node_CommutativeAssociativeBinaryOperator,
                     K2Node_EnhancedInputAction, K2Node_DynamicCast, K2Node_FlipFlop,
                     K2Node_Select, K2Node_MakeStruct, K2Node_BreakStruct,
                     K2Node_VariableSet, K2Node_Timeline, K2Node_InputAction, K2Node_InputAxisEvent,
                     K2Node_InputKey, K2Node_GetClassDefaults, K2Node_MakeArray, K2Node_MakeMap,
                     K2Node_GetArrayItem, # K2Node_GetArrayItem already imported in the original second block
                     K2Node_InputTouch, K2Node_InputAxisKeyEvent, K2Node_InputDebugKey,
                     K2Node_GenericCreateObject, K2Node_CreateWidget, K2Node_AddComponent,
                     K2Node_SpawnActorFromClass, K2Node_CreateDelegate, K2Node_CustomEvent, K2Node_Event,
                     K2Node_SetFieldsInStruct, K2Node_FormatText, K2Node_FunctionResult, K2Node_FunctionEntry,
                     K2Node_MacroInstance, K2Node_GetSubsystem,
                     K2Node_Literal, K2Node_CallArrayFunction, K2Node_ComponentBoundEvent, K2Node_ActorBoundEvent # Added based on request and revision
                     )
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
        # --- (Keep MATH_OPERATORS and TYPE_CONVERSIONS, expanded MATH_OPERATORS) ---
        self.MATH_OPERATORS = { # More extensive mapping
            "Divide": "/", "Add": "+", "Subtract": "-", "Multiply": "*",
            "Less": "<", "Greater": ">", "LessEqual": "<=", "GreaterEqual": ">=",
            "EqualEqual": "==", "NotEqual": "!=",
            "BooleanAND": "AND", "BooleanOR": "OR", "BooleanXOR": "XOR", "BooleanNAND": "NAND",
            "Max": "MAX", "Min": "MIN", "FMax": "MAX", "FMin": "MIN",
            "Percent": "%", "BooleanNOT": "NOT",
            # Add vector/rotator ops if needed: e.g., "Multiply_VectorFloat": "*", "Add_VectorVector": "+"
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
            # Add function based conversions if needed, e.g. ToText (Int) etc.
            "Conv_IntToText": "Text", "Conv_FloatToText": "Text", "Conv_StringToText": "Text", "Conv_NameToText": "Text",
            "Conv_ByteToText": "Text", "Conv_BoolToText": "Text", "Conv_VectorToString": "string",
            # Common functions acting as conversions
            "ToString (Vector)": "string", "ToString (Rotator)": "string", "ToString (Object)": "string",
            # ... potentially more based on common library functions
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

        # --- NEW: K2Node_Literal ---
        if isinstance(source_node, K2Node_Literal):
            # K2Node_Literal might store the value directly in the node or the output pin's default
            literal_output_pin = source_node.get_output_pin()
            if literal_output_pin:
                # Check both node property and pin default (prefer pin default as it's usually set)
                literal_value = literal_output_pin.default_value or getattr(source_node, 'value', None)
                # Even if a 'value' property exists, the default_value on the pin is often more accurate
                # Use _format_default_value which handles various types correctly
                return self._format_default_value(literal_output_pin)
            # Fallback if pin or value not found (should be rare)
            return span("bp-error", "[Literal Value?]")
        # --- END NEW ---

        # --- Existing Specific Node Handling ---
        elif isinstance(source_node, K2Node_GetSubsystem):
            if source_pin == source_node.get_return_value_pin():
                subsystem_name = source_node.get_subsystem_class_name() or "UnknownSubsystem"
                target_str = ""
                # K2Node_GetSubsystemFromPC is a specific subclass we might need to check
                # For now, assume a potential PlayerController pin exists on some variants
                pc_pin_name = "PlayerController" # Common name
                pc_pin = source_node.get_pin(pc_pin_name)
                if pc_pin and pc_pin.is_input(): # Ensure it's an input pin
                    pc_str = self._resolve_pin_value_recursive(pc_pin, depth + 1, visited_pins.copy())
                    # Only add "from" if the resolved value isn't the default/implicit 'self'
                    if pc_str != span("bp-var", "`self`"):
                        target_str = f" from {pc_str}"
                return f"{span('bp-keyword', 'GetSubsystem')}({span('bp-class-name', f'`{subsystem_name}`')}){target_str}"
            else:
                return f"{span('bp-info', 'ValueFrom')}({span('bp-node-type', source_node.node_type)}.{span('bp-pin-name', f'`{source_pin.name}`')})"

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

        # --- REVISED: Event/Input Parameter Handling ---
        elif isinstance(source_node, (K2Node_FunctionEntry, K2Node_Event, K2Node_CustomEvent,
                                      K2Node_EnhancedInputAction, K2Node_InputAction, K2Node_InputAxisEvent,
                                      K2Node_InputKey, K2Node_InputTouch, K2Node_InputAxisKeyEvent, K2Node_InputDebugKey,
                                      K2Node_ComponentBoundEvent, K2Node_ActorBoundEvent)):
            # --- DEBUG PRINT ---
            if ENABLE_TRACER_DEBUG: print(f"{indent}  -> Checking Event/Input Handler for Node Type: {type(source_node).__name__}, Pin: {source_pin.name}", file=sys.stderr)
            # --- END DEBUG ---

            # Handle output data pins from Events/Inputs/Function Entries
            if source_pin.is_output() and not source_pin.is_execution():
                # --- Determine Event/Function Name (Keep this logic) ---
                event_name = "Event" # Default
                # Use getattr with fallback for various potential name properties
                event_name = getattr(source_node, 'custom_function_name', None) or \
                             getattr(source_node, 'event_function_name', None) or \
                             getattr(source_node, 'input_action_name', None) or \
                             getattr(source_node, 'action_name', None) or \
                             getattr(source_node, 'axis_name', None) or \
                             getattr(source_node, 'input_key_name', None) or \
                             getattr(source_node, 'axis_key_name', None) or \
                             getattr(source_node, 'delegate_property_name', None) or \
                             extract_member_name(getattr(source_node, 'FunctionReference', None)) or \
                             source_node.node_type # Fallback to node type if no name found

                # Handle specific event names like BeginPlay, Tick
                name_map = {"ReceiveBeginPlay": "BeginPlay", "ReceiveTick": "Tick"}
                event_name = name_map.get(event_name, event_name)

                # --- REMOVED ERRONEOUS CHECK ---
                # This check was causing the AttributeError. The getattr logic above handles it.
                # --- END REMOVAL ---

                # --- DEBUG PRINT ---
                if ENABLE_TRACER_DEBUG: print(f"{indent}    -> Identified as Output Data Pin. Attempting to return formatted name: {event_name}.{source_pin.name}", file=sys.stderr)
                # --- END DEBUG ---

                result_string = f"{span('bp-event-name', f'`{event_name}`')}.{span('bp-param-name', f'`{source_pin.name}`')}"
                # --- DEBUG PRINT ---
                if ENABLE_TRACER_DEBUG: print(f"{indent}    -> Formatted String: {result_string}", file=sys.stderr)
                # --- END DEBUG ---
                return result_string
            else:
                 # --- DEBUG PRINT ---
                 if ENABLE_TRACER_DEBUG: print(f"{indent}    -> Pin '{source_pin.name}' is NOT an Output Data Pin for this Event/Input node. Falling through to generic handling.", file=sys.stderr)
                 # --- END DEBUG ---
                 pass # Fall through
        # --- END REVISED ---


        # --- Operators / Conversions (MODIFIED) ---
        elif isinstance(source_node, (K2Node_PromotableOperator, K2Node_CommutativeAssociativeBinaryOperator)):
            # Check if it's a known conversion first
            op_name = getattr(source_node, 'operation_name', None) or getattr(source_node, 'function_name', None)
            # Normalize common conversion function names if needed (e.g., ToText (Int) -> Conv_IntToText)
            normalized_op_name = self._normalize_conversion_name(op_name)

            if normalized_op_name and normalized_op_name in self.TYPE_CONVERSIONS:
                return self._format_conversion(source_node, source_pin, depth, visited_pins.copy())
            else: # Otherwise, format as operator
                return self._format_operator(source_node, source_pin, depth, visited_pins.copy())
        # Handle CallFunction nodes that are actually conversions
        elif isinstance(source_node, K2Node_CallFunction):
            func_name = source_node.function_name
            normalized_func_name = self._normalize_conversion_name(func_name)

            if normalized_func_name and normalized_func_name in self.TYPE_CONVERSIONS:
                return self._format_conversion(source_node, source_pin, depth, visited_pins.copy())
            # Handle pure function calls normally if not a conversion
            elif source_node.is_pure_call:
                return self._format_pure_function_call(source_node, source_pin, depth, visited_pins.copy())
            # If it's not a conversion and not pure, it shouldn't produce a data value traced here
            # Fallback will handle it if needed, but ideally this branch isn't hit for data tracing

        # --- Array Operations (NEW / MODIFIED) ---
        elif isinstance(source_node, K2Node_MakeArray):
            item_pins = source_node.get_item_pins()
            # Pass copy for recursive calls
            item_strs = [self._resolve_pin_value_recursive(p, depth + 1, visited_pins.copy()) for p in item_pins]
            return f"{span('bp-literal-container', '[')}{', '.join(item_strs)}{span('bp-literal-container', ']')}"

        elif isinstance(source_node, K2Node_GetArrayItem):
            array_pin = source_node.get_target_pin()
            index_pin = source_node.get_index_pin()
            # Pass copy for recursive calls
            array_str = self._resolve_pin_value_recursive(array_pin, depth + 1, visited_pins.copy()) if array_pin else span("bp-error", "<?>")
            index_str = self._resolve_pin_value_recursive(index_pin, depth + 1, visited_pins.copy()) if index_pin else span("bp-error", "<?>")
            # Use simplified representation Array[Index]
            if re.match(r'^<span class="bp-var">`[a-zA-Z0-9_]+`</span>$', array_str):
                return f"{array_str}{span('bp-operator', '[')}{index_str}{span('bp-operator', ']')}"
            else: # Wrap complex array sources
                return f"({array_str}){span('bp-operator', '[')}{index_str}{span('bp-operator', ']')}"

        elif isinstance(source_node, K2Node_CallArrayFunction):
            # array_function_name comes from node properties
            func_name = source_node.array_function_name or "ArrayOp"
            array_pin = source_node.get_target_pin() # Usually named 'Target Array'
            # Pass copy for recursive calls
            array_str = self._resolve_pin_value_recursive(array_pin, depth + 1, visited_pins.copy()) if array_pin else span("bp-error", "<?>")
            # Format array source nicely (wrap if complex)
            array_str_fmt = array_str if re.match(r'^<span class="bp-var">`[a-zA-Z0-9_]+`</span>$', array_str) else f"({array_str})"

            # Check if we are tracing the return value pin (e.g., from Length, Find, Get, IsValidIndex)
            if source_pin == source_node.get_return_value_pin():
                # Format based on common array functions returning values
                if func_name == "Length":
                    return f"{array_str_fmt}.{span('bp-func-name', 'Length')}()"
                elif func_name == "IsValidIndex":
                    index_pin = source_node.get_index_pin() # Pin usually named 'Index'
                    index_str = self._resolve_pin_value_recursive(index_pin, depth + 1, visited_pins.copy()) if index_pin else span("bp-error", "<?>")
                    return f"{array_str_fmt}.{span('bp-func-name', 'IsValidIndex')}({index_str})"
                elif func_name == "Find":
                    item_pin = source_node.get_item_pin() # Pin usually named 'ItemToFind'
                    item_str = self._resolve_pin_value_recursive(item_pin, depth + 1, visited_pins.copy()) if item_pin else span("bp-error", "<?>")
                    # Find usually returns the index
                    return f"{array_str_fmt}.{span('bp-func-name', 'Find')}({item_str})"
                elif func_name == "Contains":
                    item_pin = source_node.get_item_pin() # Pin named 'ItemToFind'
                    item_str = self._resolve_pin_value_recursive(item_pin, depth + 1, visited_pins.copy()) if item_pin else span("bp-error", "<?>")
                    return f"{array_str_fmt}.{span('bp-func-name', 'Contains')}({item_str})"
                elif func_name == "Get":
                    index_pin = source_node.get_index_pin()
                    index_str = self._resolve_pin_value_recursive(index_pin, depth + 1, visited_pins.copy()) if index_pin else span("bp-error", "<?>")
                    # Mimic array access notation for Get's return value
                    return f"{array_str_fmt}{span('bp-operator', '[')}{index_str}{span('bp-operator', ']')}"
                else: # Default format for less common or unknown return values
                    exclude = {array_pin.name.lower()} if array_pin and array_pin.name else set()
                    # Exclude output pins if they somehow appear as inputs (unlikely but safe)
                    for p in source_node.get_output_pins():
                        if p.name: exclude.add(p.name.lower())
                    args_str = self._format_arguments_for_trace(source_node, depth + 1, visited_pins.copy(), exclude_pins=exclude)
                    return f"{span('bp-info', 'ResultOf')}({array_str_fmt}.{span('bp-func-name', f'`{func_name}`')}({args_str}))"

            # Check if we are tracing the output array pin (passthrough after modification)
            elif source_pin == source_node.get_output_array_pin():
                # Represent the modification action as the value source for clarity
                if func_name == "Add":
                    item_pin = source_node.get_item_pin() # Pin usually named like 'New Item'
                    item_str = self._resolve_pin_value_recursive(item_pin, depth + 1, visited_pins.copy()) if item_pin else span("bp-error", "<?>")
                    return f"{span('bp-info','ResultOf')}({array_str_fmt}.{span('bp-func-name', 'Add')}({item_str}))"
                elif func_name == "RemoveIndex":
                    index_pin = source_node.get_index_pin() # Pin usually named 'Index'
                    index_str = self._resolve_pin_value_recursive(index_pin, depth + 1, visited_pins.copy()) if index_pin else span("bp-error", "<?>")
                    return f"{span('bp-info','ResultOf')}({array_str_fmt}.{span('bp-func-name', 'RemoveAt')}({index_str}))"
                elif func_name == "SetArrayElem":
                    index_pin = source_node.get_index_pin() # Pin named 'Index'
                    item_pin = source_node.get_item_pin() # Pin named 'Item'
                    index_str = self._resolve_pin_value_recursive(index_pin, depth + 1, visited_pins.copy()) if index_pin else span("bp-error", "<?>")
                    item_str = self._resolve_pin_value_recursive(item_pin, depth + 1, visited_pins.copy()) if item_pin else span("bp-error", "<?>")
                    # Represent Set as an assignment-like operation for clarity in trace
                    return f"{span('bp-info','ResultOf')}({array_str_fmt}[{index_str}] = {item_str})"
                # Add other modifying functions: Insert, RemoveItem, Clear etc.
                else: # Default for other modifying functions
                    exclude = {array_pin.name.lower()} if array_pin and array_pin.name else set()
                    # Exclude output pins if they somehow appear as inputs
                    for p in source_node.get_output_pins():
                        if p.name: exclude.add(p.name.lower())
                    args_str = self._format_arguments_for_trace(source_node, depth + 1, visited_pins.copy(), exclude_pins=exclude)
                    return f"{span('bp-info', 'Modified')}({array_str_fmt}.{span('bp-func-name', f'`{func_name}`')}({args_str}))"

            else: # Tracing some other output pin (less common for array functions)
                return f"{span('bp-info', 'ValueFrom')}({array_str_fmt}.{span('bp-func-name', f'`{func_name}`')}.{span('bp-pin-name', f'`{source_pin.name}`')})"
        # --- END Array Operations ---


        # --- Existing Pure Function / Macro Handling (Make sure CallFunction was handled above if it's a conversion or pure) ---
        # elif isinstance(source_node, K2Node_CallFunction) and source_node.is_pure_call: # Handled above
        #     pass
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
                 cast_type_raw = source_node.target_type or "UnknownType"
                 cast_type = extract_simple_name_from_path(cast_type_raw) # Simplify path
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
                struct_type_raw = source_node.struct_type or "Struct"
                struct_type = extract_simple_name_from_path(struct_type_raw)
                args = []
                # Include hidden pins potentially, but filter trivial defaults
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

        elif isinstance(source_node, K2Node_BreakStruct):
            input_pin = source_node.get_input_struct_pin()
            input_str = self._resolve_pin_value_recursive(input_pin, depth + 1, visited_pins.copy()) if input_pin else span("bp-error", "<?>") # Pass copy
            member_name = source_pin.name or "UnknownMember"
            # Only use dot notation if the input is clearly a simple variable
            if re.match(r'^<span class="bp-var">`[a-zA-Z0-9_]+`</span>$', input_str):
                 return f"{input_str}.{span('bp-pin-name', f'`{member_name}`')}"
            else:
                 return f"({input_str}).{span('bp-pin-name', f'`{member_name}`')}"

        elif isinstance(source_node, K2Node_MakeMap):
            item_pairs = source_node.get_item_pins()
            pair_strs = [f"{self._resolve_pin_value_recursive(k, depth + 1, visited_pins.copy())} {span('bp-operator', ':')} {self._resolve_pin_value_recursive(v, depth + 1, visited_pins.copy())}" for k,v in item_pairs] # Pass copy
            return f"{span('bp-literal-container', '{')}{', '.join(pair_strs)}{span('bp-literal-container', '}')}"

        # elif isinstance(source_node, K2Node_GetArrayItem): # Already handled above
        #     pass

        elif isinstance(source_node, K2Node_CreateDelegate):
            func_name_pin = source_node.get_function_name_pin()
            # Pass copy when resolving pins
            # Use the raw property 'FunctionName' as fallback for the literal name
            func_name_str = self._resolve_pin_value_recursive(func_name_pin, depth + 1, visited_pins.copy()) if func_name_pin and func_name_pin.linked_pins else span("bp-literal-name", f"`{source_node.raw_properties.get('FunctionName', '?')}`")
            obj_pin = source_node.get_object_pin()
            obj_str = self._resolve_pin_value_recursive(obj_pin, depth + 1, visited_pins.copy()) if obj_pin else span("bp-var", "`self`")
            return f"{span('bp-keyword', 'Delegate')}({func_name_str} {span('bp-keyword', 'on')} {obj_str})"

        elif source_node.ue_class == "/Script/BlueprintGraph.K2Node_Self":
            return span("bp-var", "`self`")

        # elif source_node.ue_class == "/Script/BlueprintGraph.K2Node_Literal": # Instance check K2Node_Literal preferred and handled earlier
        #     pass

        # --- Fallback for other unhandled nodes ---
        else:
            # Try formatting via NodeFormatter for a general description
            # Avoid infinite recursion: don't call node_formatter if already inside it?
            # For now, assume simple fallback is safer here.
            # Consider a flag to prevent recursive node formatting if issues arise.

            # Simpler Fallback:
            node_type_str = source_node.node_type or source_node.ue_class.split('.')[-1]
            pin_name_str = source_pin.name or "Output"
            return f"{span('bp-info', 'ValueFrom')}({span('bp-node-type', f'`{node_type_str}`')}.{span('bp-pin-name', f'`{pin_name_str}`')})"

            # Original Fallback using NodeFormatter (might be too complex/recursive):
            # formatter_desc, _ = self.node_formatter.format_node(source_node, "", set()) # Use empty prefix/visited for description
            # if formatter_desc:
            #     action_part = formatter_desc.split("-->")[-1].strip() # Get part after arrow if exists
            #     action_part = re.sub(r'\s*\(.*\)\s*$', '', action_part).strip() # Remove trailing args ()
            #     action_part = action_part.replace("**", "").replace("`", "") # Clean up markdown
            #     action_part = re.sub(r'<[^>]+>', '', action_part) # Strip remaining HTML spans
            #     pin_name_str = f".{span('bp-pin-name', f'`{source_pin.name}`')}" if source_pin.name and source_pin.name != "ReturnValue" else ""
            #     # Avoid overly verbose fallback if it's just the node type
            #     if action_part.lower() == source_node.node_type.lower():
            #         return f"{span('bp-info', 'ValueFrom')}({span('bp-node-type', f'`{source_node.node_type}`')}.{span('bp-pin-name', f'`{source_pin.name}`')})"
            #     else:
            #         return f"{span('bp-info', 'ResultOf')}({span('bp-generic-node', action_part)}){pin_name_str}"
            # else:
            #     # Ultimate fallback if node formatting fails
            #     return f"{span('bp-info', 'ValueFrom')}({span('bp-node-type', f'`{source_node.node_type}`')}.{span('bp-pin-name', f'`{source_pin.name}`')})"

        # This line should ideally not be reached if all cases are handled
        # return span("bp-error", f"[Unhandled Node Type Fallback: {source_node.node_type}]") # Covered by else above

    # --- MODIFIED: Use Symbols ---
    def _format_operator(self, node: Node, output_pin: Pin, depth: int, visited_pins: Set[str]) -> str:
        """Formats promotable/commutative operators symbolically."""
        # Get operation name (can be function_name for some nodes)
        op_name = getattr(node, 'operation_name', None) or getattr(node, 'function_name', 'Op')
        symbol = self.MATH_OPERATORS.get(op_name)
        inputs = node.get_input_pins(exclude_exec=True, include_hidden=False)
        # Sort inputs deterministically (e.g., A, B, C...)
        inputs.sort(key=lambda p: (0 if p.name in ['A', 'B', 'C', 'D', 'E', 'Index'] else 1, p.name or ""))
        # Pass copy for recursive calls
        input_vals = [self._resolve_pin_value_recursive(p, depth + 1, visited_pins.copy()) for p in inputs]

        if symbol and len(input_vals) == 2:
            # Basic infix formatting
            return f"({input_vals[0]} {span('bp-operator', symbol)} {input_vals[1]})"
        elif symbol and len(input_vals) == 1:
             # Handle unary operators like NOT
             if op_name == "BooleanNOT":
                 return f"{span('bp-keyword', 'NOT')} ({input_vals[0]})"
             # Add other unary math symbols if needed (e.g., Abs, Negate)
             # Fallback to func name for unary ops without a dedicated symbol or prefix symbol
             return f"{span('bp-operator', symbol)}{input_vals[0]}" # Assume prefix if symbol exists
        # --- Remove specific SelectFloat, Lerp, Interp, Concat logic here - handled by pure function or dedicated node types ---
        # Fallback for other operators not mapped to symbols or with != 1 or 2 inputs
        return f"{span('bp-func-name', op_name)}({', '.join(input_vals)})"

    # --- NEW: Format Conversion ---
    def _format_conversion(self, node: Node, output_pin: Pin, depth: int, visited_pins: Set[str]) -> str:
        """Formats type conversion nodes."""
        # Get function/operation name that matched the conversion lookup
        func_name = getattr(node, 'function_name', None) or getattr(node, 'operation_name', 'Conv')
        # Handle potential normalized names used in the lookup
        normalized_func_name = self._normalize_conversion_name(func_name)

        target_type = self.TYPE_CONVERSIONS.get(normalized_func_name or func_name, "UnknownType") # Fallback to original name if normalization fails

        # Find the single primary input data pin (heuristic: first non-exec input)
        input_pin = next((p for p in node.get_input_pins(exclude_exec=True, include_hidden=False)), None)
        # Fallback if heuristic fails (e.g., pin named 'Input Pin' or 'Value')
        if not input_pin and hasattr(node, 'get_pin'):
             input_pin = node.get_pin("Input Pin") or node.get_pin("Value") # Common names

        # Pass copy for recursive calls
        input_val_str = self._resolve_pin_value_recursive(input_pin, depth + 1, visited_pins.copy()) if input_pin else span("bp-error", "<?>")

        # Format as Type(Value)
        return f"{span('bp-data-type', target_type)}({input_val_str})"
    # --- END NEW ---

    # Helper to normalize conversion function names like "ToString (Vector)" -> "Conv_VectorToString"
    def _normalize_conversion_name(self, func_name: Optional[str]) -> Optional[str]:
        if not func_name: return None

        # Direct match is fastest
        if func_name in self.TYPE_CONVERSIONS:
            return func_name

        # Handle patterns like "ToText (Int)" -> "Conv_IntToText"
        if func_name.startswith("To") and " (" in func_name and func_name.endswith(")"):
            match = re.match(r"^(.*?)\s*\((.*?)\)$", func_name)
            if match:
                base_func, input_type = match.groups()
                # Construct a potential key like Conv_InputToBaseFunc
                conv_key = f"Conv_{input_type.replace(' ', '')}To{base_func}"
                if conv_key in self.TYPE_CONVERSIONS:
                    return conv_key
        return None # Return None if no match or normalization found

    # --- (Keep _format_pure_function_call, _format_pure_macro_call) ---
    # Make sure _format_pure_function_call handles math functions that *weren't* caught by _format_operator
    def _format_pure_function_call(self, node: K2Node_CallFunction, output_pin: Pin, depth: int, visited_pins: Set[str]) -> str:
        """Formats pure K2Node_CallFunction symbolically."""
        # Check if it should have been handled as a conversion first
        func_name = node.function_name or 'PureFunc'
        normalized_func_name = self._normalize_conversion_name(func_name)

        if normalized_func_name and normalized_func_name in self.TYPE_CONVERSIONS:
             # Should have been caught earlier, but handle defensively
             return self._format_conversion(node, output_pin, depth, visited_pins.copy())

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
            # Uses simplified check based on common formats from _format_literal_value
            is_empty_tag_container = (
                           tag_value_str == "Empty" or
                           tag_value_str == span("bp-info", "(No Default)") or
                           tag_value_str == f"{span('bp-literal-struct-type', '`0`')} {span('bp-info','Tags')}" or
                           tag_value_str == f"{span('bp-literal-struct-type', '`GameplayTagContainer`')}({span('bp-literal-struct-val', '()')})" or
                           tag_value_str == f"{span('bp-literal-struct-type', '`GameplayTagContainer`')}({span('bp-literal-unknown', '...')})" or
                           tag_value_str == ""
                           )

            if is_empty_tag_container:
                return f"{span('bp-func-name', 'EmptyTagContainer')}()"
            else:
                return f"{span('bp-func-name', 'MakeTagContainer')}({span('bp-param-name', 'Value')}={tag_value_str})" # Use simpler name
        # --- END SPECIFIC ---

        # --- Handle common math library functions not covered by operators ---
        # Example: Lerp (often a pure function)
        if func_name == "Lerp" and len([p for p in node.get_input_pins(exclude_exec=True) if p.name in ['A', 'B', 'Alpha']]) == 3:
             a_pin = node.get_pin("A")
             b_pin = node.get_pin("B")
             alpha_pin = node.get_pin("Alpha")
             # Pass copy for recursive calls
             a_val = self._resolve_pin_value_recursive(a_pin, depth + 1, visited_pins.copy()) if a_pin else span("bp-error", "??")
             b_val = self._resolve_pin_value_recursive(b_pin, depth + 1, visited_pins.copy()) if b_pin else span("bp-error", "??")
             alpha_val = self._resolve_pin_value_recursive(alpha_pin, depth + 1, visited_pins.copy()) if alpha_pin else span("bp-error", "??")
             return f"{span('bp-func-name', 'Lerp')}({a_val}, {b_val}, {span('bp-param-name', 'Alpha')}={alpha_val})"
        # Example: Select Float/String/etc. (often pure functions)
        # These look like K2Node_Select but are function calls
        if func_name.startswith("Select") and node.get_pin("Pick A"):
             a_pin = node.get_pin("A")
             b_pin = node.get_pin("B")
             pick_a_pin = node.get_pin("Pick A") or node.get_pin("PickA") # Allow variation
             # Pass copy for recursive calls
             a_val = self._resolve_pin_value_recursive(a_pin, depth + 1, visited_pins.copy()) if a_pin else span("bp-error", "??")
             b_val = self._resolve_pin_value_recursive(b_pin, depth + 1, visited_pins.copy()) if b_pin else span("bp-error", "??")
             cond_val = self._resolve_pin_value_recursive(pick_a_pin, depth + 1, visited_pins.copy()) if pick_a_pin else span("bp-error", "???")
             # Use ternary operator style
             return f"({cond_val} {span('bp-operator', '?')} {a_val} {span('bp-operator', ':')} {b_val})"

        # --- General Pure Function Formatting ---
        # Pass copy when resolving target pin
        target_str_raw = self._resolve_pin_value_recursive(target_pin, depth + 1, visited_pins.copy()) if target_pin else span("bp-var", "`self`")

        exclude_pins = {target_pin.name.lower()} if target_pin and target_pin.name else set()
        args_str = self._format_arguments_for_trace(node, depth + 1, visited_pins.copy(), exclude_pins=exclude_pins)

        # Determine if it's a static call based on target resolution
        is_static_call = False
        # --- ADDED None check ---
        if target_str_raw:
            # Check if target looks like a class name or default object, not 'self'
            match_class_default = re.match(r'^(?:<span class="bp-var">)?`?([a-zA-Z0-9_]+)`?(?:</span>)?(?:|::(?:<span class="bp-keyword">)?Default(?:</span>)?)?$', target_str_raw)
            match_class_only = re.match(r'^<span class="bp-class-name">`([a-zA-Z0-9_]+)`</span>$', target_str_raw)
            match_object_path = re.match(r'^<span class="bp-literal-object">`([a-zA-Z0-9_/.:]+)`</span>$', target_str_raw) # Match literal object paths

            if match_class_default and match_class_default.group(1) != 'self':
                is_static_call = True
            elif match_class_only and match_class_only.group(1) != 'self':
                is_static_call = True
            elif match_object_path and match_object_path.group(1) != 'self':
                # Check if it's a default object path
                if 'Default__' in match_object_path.group(1):
                    is_static_call = True
                # Otherwise, might be a specific object instance, treat as non-static unless known library
                # We can improve this with a list of known static function libraries if needed
            elif target_str_raw.startswith(span("bp-var", "`Default__")): # Default library object
                is_static_call = True # Treat these like static calls for formatting


        call_prefix = ""
        # --- ADDED None check ---
        if target_str_raw:
            target_cleaned = target_str_raw.replace('&amp;', '&').replace('&lt;', '<').replace('&gt;', '>') # Decode HTML entities for checks
            if target_cleaned == span("bp-var", "`self`"):
                 call_prefix = "" # Implicit self
            elif is_static_call:
                # Extract class name if Default__ prefix exists or if it's ClassName::Default
                class_name_match = re.match(r'^(?:<span class="(?:bp-var|bp-literal-object)">)?`?(?:Default__)?([a-zA-Z0-9_]+)`?(?:</span>)?(?:|::(?:<span class="bp-keyword">)?Default(?:</span>)?)?$', target_cleaned)
                class_only_match = re.match(r'^<span class="bp-class-name">`([a-zA-Z0-9_]+)`</span>$', target_cleaned)

                class_name = None
                if class_name_match: class_name = class_name_match.group(1)
                elif class_only_match: class_name = class_only_match.group(1)

                if class_name and class_name not in ['KismetSystemLibrary', 'KismetMathLibrary', 'GameplayStatics', 'KismetStringLibrary', 'KismetArrayLibrary']: # Hide common static libs
                    call_prefix = f"{span('bp-class-name', f'`{class_name}`')}." # Use class name
                else:
                    call_prefix = "" # Hide prefix for common static libraries or if class name extraction failed
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
        primary_output_pin = node.get_return_value_pin() # Usually named 'ReturnValue'
        base_call = f"{call_prefix}{func_name_span}({args_str})"

        # Check if the pin being traced is the primary return value
        if output_pin == primary_output_pin or not primary_output_pin or output_pin.name == 'ReturnValue':
            return base_call
        else:
            # If tracing a secondary output pin of a pure function (less common, e.g., a boolean success flag)
            return f"({base_call}).{span('bp-pin-name', f'`{output_pin.name}`')}"


    def _format_pure_macro_call(self, node: K2Node_MacroInstance, output_pin: Pin, depth: int, visited_pins: Set[str]) -> str:
        # Similar logic to pure functions, but macros don't have a 'target' in the same way
        macro_name = node.macro_type or "PureMacro"
        macro_name = extract_simple_name_from_path(macro_name) # Clean up path if present

        # Pass copy for recursive calls
        args_str = self._format_arguments_for_trace(node, depth + 1, visited_pins.copy())

        # Heuristic: find the first non-exec output pin as the "primary"
        primary_output_pin = next((p for p in node.get_output_pins() if not p.is_execution()), None)
        base_call = f"{span('bp-func-name', f'`{macro_name}`')}({args_str})" # Use bp-func-name for macros too

        if output_pin == primary_output_pin or not primary_output_pin:
             return base_call
        else:
             # Append the specific output pin name if it's not the primary one
             return f"({base_call}).{span('bp-pin-name', f'`{output_pin.name}`')}"


    # --- (Keep _format_default_value, _format_literal_value, _is_trivial_default, _trace_target_pin) ---
    def _format_default_value(self, pin: Pin) -> str:
        val = pin.default_value; obj = pin.default_object; struct = pin.default_struct
        # Prioritize default_value as it's often set directly for literals
        if val is not None: return self._format_literal_value(pin, val)
        # Then check default_object
        if obj and obj.lower() != 'none':
             # Format as an object literal
             return self._format_literal_value(pin, obj) # Pass object path/name
        # Then check default_struct representation
        if struct is not None: return self._format_literal_value(pin, str(struct)) # Pass struct default string representation

        # Implicit self for common input names
        if pin.name and pin.name.lower() in ['self', 'target', 'worldcontextobject'] and pin.is_input():
             return span("bp-var", "`self`")

        # Return default literals wrapped in spans based on category if nothing else is set
        if pin.category == 'bool': return span("bp-literal-bool", "false")
        if pin.category in ['byte', 'int', 'int64', 'real', 'float', 'double']: return span("bp-literal-number", "0")
        if pin.category in ['string', 'text']: return span("bp-literal-string", "''")
        if pin.category in ['name']: return span("bp-literal-name", "`None`")
        if pin.category in ['object', 'class', 'interface', 'asset', 'assetclass', 'softobject', 'softclass']: return span("bp-literal-object", "`None`")
        if pin.container_type in ['Array', 'Set', 'Map']: return span("bp-literal-container", "[]" if pin.container_type == 'Array' else "{}")
        # Default for structs if no struct string was provided
        if pin.category == 'struct':
            struct_name = extract_simple_name_from_path(pin.sub_category_object) if pin.sub_category_object else "Struct"
            return f"{span('bp-literal-struct-type', f'`{struct_name}`')}({span('bp-literal-unknown', '...')})" # Represent as empty/default struct

        return span("bp-info", "(No Default)")

    def _format_literal_value(self, pin: Pin, val_str: str) -> str:
        """Formats literal values with proper escaping and type-specific styling."""
        category = pin.category
        sub_category_obj = pin.sub_category_object

        val_str = str(val_str).strip()
        # Handle potential object path strings passed directly (heuristic: contains / or :, or is quoted)
        is_path = '/' in val_str or ':' in val_str or (val_str.startswith("'") and val_str.endswith("'") and len(val_str)>2) or (val_str.startswith('"') and val_str.endswith('"') and len(val_str)>2)

        # Remove outer quotes carefully, preserving internal quotes and avoiding removal from simple "0" etc.
        original_val_str = val_str # Keep original for struct parsing
        if len(val_str) >= 2 and val_str.startswith('"') and val_str.endswith('"'):
             val_str = val_str[1:-1]
        elif len(val_str) >= 2 and val_str.startswith("'") and val_str.endswith("'"):
             val_str = val_str[1:-1]


        # Escape backticks within names/strings/paths for display in `` or ''
        # Basic HTML escaping done by span() helper
        escaped_val_str = val_str.replace('`', r'\`')

        # --- Object/Class Handling ---
        if category in ['object', 'class', 'asset', 'assetclass', 'softobject', 'softclass', 'interface']:
             # Use original value string for path check as quotes might be significant
             is_path_orig = '/' in original_val_str or ':' in original_val_str or (original_val_str.startswith("'") and original_val_str.endswith("'") and len(original_val_str)>2) or (original_val_str.startswith('"') and original_val_str.endswith('"') and len(original_val_str)>2)

             if is_path_orig:
                 # Use original value string for extraction
                 simple_name = extract_simple_name_from_path(original_val_str.strip("'\"")) # Strip quotes before extracting
                 if simple_name and simple_name.lower() != 'none':
                     return span("bp-literal-object", f"`{simple_name}`")
                 else: # Fallback if path parsing fails or yields None
                     # Use the (potentially quote-stripped) escaped_val_str
                     if escaped_val_str.lower() == 'none' or not escaped_val_str:
                         return span("bp-literal-object", "`None`")
                     else:
                         return span("bp-literal-object", f"`{escaped_val_str}`") # Use potentially quote-stripped value
             elif escaped_val_str.lower() == 'none' or not escaped_val_str:
                 return span("bp-literal-object", "`None`")
             else:
                 return span("bp-literal-object", f"`{escaped_val_str}`") # Non-path, non-None object name

        # --- Bool Handling ---
        if category == 'bool': return span("bp-literal-bool", escaped_val_str.lower())

        # --- Numeric/Enum Handling ---
        if category in ['byte', 'int', 'int64']:
            if sub_category_obj and ('Enum' in sub_category_obj or sub_category_obj.endswith('_UENUM')):
                enum_type = extract_simple_name_from_path(sub_category_obj) or "Enum"
                enum_val_str = escaped_val_str.split("::")[-1].split('.')[-1] # Get value part
                return f"{span('bp-enum-type', f'`{enum_type}`')}::{span('bp-enum-value', f'`{enum_val_str}`')}"
            try: return span("bp-literal-number", str(int(float(escaped_val_str)))) # Use float conversion to handle potential ".0"
            except (ValueError, TypeError): return span("bp-literal-unknown", escaped_val_str) # Handle non-numeric gracefully
        if category in ['real', 'float', 'double']:
            try:
                num_val = float(escaped_val_str)
                if num_val.is_integer(): return span("bp-literal-number", str(int(num_val)))
                # Format nicely, remove trailing zeros, limit precision
                formatted = f"{num_val:.4f}".rstrip('0').rstrip('.')
                return span("bp-literal-number", formatted if formatted and formatted != '-' else '0.0')
            except (ValueError, TypeError): return span("bp-literal-unknown", escaped_val_str) # Handle non-numeric gracefully

        # --- String/Name Handling ---
        if category in ['string', 'text']: return span("bp-literal-string", f"'{escaped_val_str}'") # Use single quotes visually
        if category == 'name': return span("bp-literal-name", "`None`" if escaped_val_str.lower() == 'none' or not escaped_val_str else f"`{escaped_val_str}`")

        # --- UPDATED Struct/Tag Handling ---
        if category == 'struct':
            struct_name = extract_simple_name_from_path(sub_category_obj) if sub_category_obj else "Struct"
            # Use the ORIGINAL value string (potentially with quotes) for parsing struct defaults
            parsed_default = parse_struct_default_value(original_val_str)

            if parsed_default:
                # Specific logic for GameplayTag based on parsed content or type name
                is_gameplay_tag = (struct_name == "GameplayTag")

                if is_gameplay_tag and isinstance(parsed_default, str):
                    # Extract just the tag name if it's in the (TagName="...") format
                    tag_name = parsed_default
                    # Match TagName="`Actual.Tag.Name`" or TagName="Actual.Tag.Name" or just Actual.Tag.Name
                    tag_match = re.match(r'^\(?\s*TagName\s*=\s*"?`?([^"`]+)`?"?\s*\)?$', tag_name, re.IGNORECASE)
                    if tag_match:
                        tag_name = tag_match.group(1)
                    # Handle cases where parse_struct_default_value might just return the tag name directly
                    elif not tag_name.startswith('('):
                        pass # Assume it's already the tag name

                    # Cleanup backtick escapes if present
                    tag_name = tag_name.replace(r'\`', '`')

                    if tag_name.lower() == 'none' or not tag_name or tag_name == '""':
                        return span("bp-literal-tag", '``') # Represent empty tag
                    else:
                        return span("bp-literal-tag", f'`{tag_name}`') # Use backticks for tag names

                # Special formatting for GameplayTagContainer (show count or ...)
                elif struct_name == "GameplayTagContainer" and isinstance(parsed_default, str):
                     tag_matches = re.findall(r'TagName\s*=\s*"?`?([^"`]+)`?"?', parsed_default, re.IGNORECASE)
                     valid_tags = [t.replace(r'\`','`').strip() for t in tag_matches if t.lower() != 'none' and t and t != '""']
                     if not valid_tags:
                         return f"{span('bp-literal-struct-type', '`0`')} {span('bp-info','Tags')}"
                     elif len(valid_tags) <= 3:
                         tags_str = ', '.join([span('bp-literal-tag', f'`{t}`') for t in valid_tags])
                         return f"{span('bp-literal-struct-type', '`{len(valid_tags)}`')} {span('bp-info','Tags')}({tags_str})"
                     else:
                         return f"{span('bp-literal-struct-type', '`{len(valid_tags)}`')} {span('bp-info','Tags')}({span('bp-literal-tag', f'`{valid_tags[0]}`')}, ...)"

                else: # General struct formatting using the parsed value
                     parsed_default_escaped = str(parsed_default).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')
                     # Basic heuristic to simplify common zero vectors/rotators
                     if struct_name in ["Vector", "Rotator", "Vector2D"] and isinstance(parsed_default, str):
                         is_zero = True
                         components = parsed_default.strip('() ').split(',')
                         # Check if ALL components are explicitly zero
                         if not components or not components[0]: is_zero = False # Empty or invalid like "()"
                         else:
                             for comp in components:
                                 key_val = comp.split('=')
                                 try:
                                     if len(key_val) == 2 and float(key_val[1].strip()) != 0.0:
                                         is_zero = False; break
                                     elif len(key_val) == 1 and float(key_val[0].strip()) != 0.0: # Handle case like "(0.0,0.0,0.0)"
                                         is_zero = False; break
                                 except: is_zero = False; break # Non-numeric component means not zero
                         if is_zero: parsed_default_escaped = "()" # Simplify to empty parens

                     return f"{span('bp-literal-struct-type', f'`{struct_name}`')}({span('bp-literal-struct-val', parsed_default_escaped)})"
            else: # Fallback for complex/unparsed structs
                 return f"{span('bp-literal-struct-type', f'`{struct_name}`')}({span('bp-literal-unknown', '...')})"
        # --- END Struct/Tag Handling Update ---

        # Fallback for completely unknown categories or unhandled values
        return span("bp-literal-unknown", escaped_val_str)


    def _is_trivial_default(self, pin: Pin) -> bool:
        if pin.linked_pins: return False # Linked pins are never using default

        val = pin.default_value; obj = pin.default_object; struct = pin.default_struct; auto_val = pin.autogenerated_default_value
        val_str = str(val).lower().strip('"\' ') if val is not None else "" # Strip spaces too
        obj_str = str(obj).lower().strip('"\' ') if obj is not None else ""
        struct_str = str(struct).strip() if struct is not None else (str(val).strip() if pin.category == 'struct' and val is not None else "") # Use struct or val if struct category

        # Check against autogenerated default first (can be efficient)
        # Compare raw string values to avoid type issues
        if val is not None and auto_val is not None:
            # Normalize quotes for comparison
            val_norm = str(val).strip().strip("'\"")
            auto_val_norm = str(auto_val).strip().strip("'\"")
            if val_norm == auto_val_norm:
                if pin.category == 'name' and val_norm.lower() == 'none': return True
                if pin.category == 'bool' and val_norm.lower() == 'false': return True
                # If default matches autogen for other simple types, consider it trivial
                if pin.category not in ['struct', 'object', 'class', 'interface', 'asset', 'assetclass', 'softobject', 'softclass']:
                    try: # Check numeric zero robustly
                         if float(val_norm) == 0.0: return True
                    except: pass
                    if val_norm == '': return True # Empty string
                    # Assume other exact matches to autogen are trivial defaults if not name/bool
                    if pin.category not in ['name', 'bool']: return True


        # Standard checks if autogen check didn't apply or didn't match trivially
        # Use normalized strings (val_str, obj_str, struct_str)
        if val is None and obj is None and struct is None: return True # Completely empty
        if pin.category in ['object', 'class', 'interface', 'asset', 'assetclass', 'softobject', 'softclass'] and obj_str in ['none', 'null', 'nullptr', '']: return True
        if pin.category in ['byte', 'int', 'int64', 'real', 'float', 'double']:
            try:
                if float(val_str) == 0.0: return True
            except (ValueError, TypeError): pass # Ignore non-numeric val_str
        if pin.category == 'bool' and val_str == 'false': return True
        if pin.category in ['string', 'text'] and val_str == '': return True
        if pin.category == 'name' and val_str == 'none': return True

        # Struct checks using struct_str
        if pin.category == 'struct':
            if struct_str == '()' or struct_str == '{}' or struct_str == '': return True # Empty struct representation
            # Parse the struct string to check components
            parsed_simple_default = parse_struct_default_value(struct_str)
            if parsed_simple_default and isinstance(parsed_simple_default, str):
                # Check for zero vector/rotator patterns more robustly
                components = parsed_simple_default.strip('() ').split(',')
                all_zero = True
                if not components or not components[0]: all_zero = False # Empty struct string like "()" isn't zero vector unless explicitly checked above
                else:
                    for comp in components:
                        comp = comp.strip()
                        if not comp: continue # Skip empty parts from trailing commas etc.
                        # Match pattern like "X=0.0" or "TagName=``" or just "0.0"
                        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*\s*=\s*(?:0(?:[.][0]*)?|false|""|``|none|None)$', comp, re.IGNORECASE): continue # Definitely zero/default
                        if re.match(r'^0(?:[.][0]*)?$', comp): continue # Just the number 0 or 0.0
                        # Check specifically for empty TagName (None or "")
                        if re.match(r'^TagName\s*=\s*(?:""|``|none|None)$', comp, re.IGNORECASE): continue
                        # If any component doesn't match a zero/default pattern, it's not trivial
                        all_zero = False
                        break
                if all_zero: return True # All components were zero/default

                # Check for empty GameplayTag via name or value using the parsed string
                struct_name = extract_simple_name_from_path(pin.sub_category_object) if pin.sub_category_object else ""
                if struct_name == "GameplayTag":
                     tag_match = re.match(r'^\(?\s*TagName\s*=\s*"?`?([^"`]+)`?"?\s*\)?$', parsed_simple_default, re.IGNORECASE)
                     tag_name = tag_match.group(1) if tag_match else parsed_simple_default
                     if tag_name.lower() == 'none' or tag_name == '""' or tag_name == "``" or not tag_name : return True

                # Check for empty GameplayTagContainer using the parsed string
                if struct_name == "GameplayTagContainer":
                    # Check if it contains ANY non-empty TagName definition
                    if not re.search(r'TagName\s*=\s*"?`?(?!none|""|``|None)[^"`]+`?"?', parsed_simple_default, re.IGNORECASE): return True # No non-empty TagName found


        # Container checks - use val_str which comes from default_value
        if pin.container_type in ["Array", "Set", "Map"] and val_str in ['()', '']: return True

        return False

    def _trace_target_pin(self, target_pin: Optional[Pin], visited_pins: Set[str]) -> str:
        """Traces the target pin, returning `self`, `ClassName::Default`, `PlayerController`, or a resolved value."""
        if not target_pin: return span("bp-var", "`self`")
        if not target_pin.linked_pins:
             # Check if target pin *itself* has a default object specified (less common but possible for static calls)
             if target_pin.default_object and target_pin.default_object.lower() != 'none':
                 # Use format_literal_value to get the correct representation (e.g., `ClassName`)
                 return self._format_literal_value(target_pin, target_pin.default_object)
             # Check common implicit target pin names
             if target_pin.name and target_pin.name.lower() in ['self', '__self__', 'target']:
                 return span("bp-var", "`self`")
             # If unlinked and no default obj, assume 'self' unless context suggests otherwise (hard to determine here)
             return span("bp-var", "`self`")

        # --- Check the SOURCE of the value for the target pin ---
        # Get the first linked pin (should be the source)
        source_pin = target_pin.linked_pins[0]
        source_node = self.parser.get_node_by_guid(source_pin.node_guid)

        if source_node:
            # Handle specific source nodes that provide common targets
            if isinstance(source_node, K2Node_GetClassDefaults):
                # Check if the source pin is THE Class Default Object output (often unnamed or 'self')
                # K2Node_GetClassDefaults output pins represent the *members*, not the class itself.
                # This case likely shouldn't resolve to ClassName::Default directly via target pin trace.
                # Instead, the pure function call formatting should handle this.
                pass # Let recursive trace handle it
            elif isinstance(source_node, K2Node_CallFunction) and source_node.function_name == "GetPlayerController":
                 if source_pin == source_node.get_return_value_pin():
                      return span("bp-var", "`PlayerController`")
            elif source_node.ue_class == "/Script/BlueprintGraph.K2Node_Self":
                 return span("bp-var", "`self`")
            # Add more special cases if needed (e.g., GetGameInstance?)

        # --- Fallback: Recursively trace the target pin normally ---
        # Pass copy for recursive calls
        # Reset depth for target trace as it's a new conceptual path start
        target_value_str = self._resolve_pin_value_recursive(target_pin, depth=0, visited_pins=visited_pins.copy())

        # Post-processing checks (simplify common patterns) - redundant with recursive call? Maybe keep for safety.
        if target_value_str == span("bp-var", "`self`"): return span("bp-var", "`self`")
        if target_value_str == span("bp-var", "`PlayerController`"): return span("bp-var", "`PlayerController`")
        # Check for ClassName::Default pattern (might occur if GetClassDefaults was traced)
        # match_class_default = re.match(r'^(<span class="bp-var">`[a-zA-Z0-9_]+`</span>)::(<span class="bp-keyword">Default</span>)', target_value_str)
        # if match_class_default: return target_value_str # Unlikely needed here, handled in pure func format

        return target_value_str

    # --- NEW HELPER (Optional): Format args specifically for trace output ---
    def _format_arguments_for_trace(self, node: Node, depth: int, visited_pins: Set[str], exclude_pins: Optional[Set[str]] = None) -> str:
         """Formats arguments for internal use in tracing, e.g., for array/pure functions."""
         if exclude_pins is None: exclude_pins = set()
         args_list = []
         # Common implicit pins to exclude from explicit argument lists
         implicit_pins = {'self', 'target', 'worldcontextobject', '__worldcontext', 'latentinfo', 'exec', '__then'}
         # Also exclude common output pin names that might appear as inputs in edge cases
         implicit_pins.update({'returnvalue', 'then'})
         # Add specific pins often implicitly handled or not shown in calls
         implicit_pins.update({'owningplayer', 'owningactor', 'spawncollisionhandlingoverride'})
         exclude_pins.update(implicit_pins)

         # Get visible, non-excluded input data pins
         input_pins = [p for p in node.get_input_pins(exclude_exec=True, include_hidden=False) if p.name and p.name.lower() not in exclude_pins]
         # Sort for deterministic output
         input_pins.sort(key=lambda p: p.name or "")

         for pin in input_pins:
             # Trace only if linked or non-trivial default
             if pin.linked_pins or not self._is_trivial_default(pin):
                 # Pass copy for recursive calls
                 pin_val = self._resolve_pin_value_recursive(pin, depth, visited_pins.copy()) # Use current depth for args
                 # Only add if value isn't considered empty/error/no-default after tracing
                 if pin_val and not pin_val.startswith('<span class="bp-error">') and pin_val != span("bp-info", "(No Default)"):
                     args_list.append(f"{span('bp-param-name', f'`{pin.name}`')}={pin_val}")

         return ", ".join(args_list)

# --- END OF FILE blueprint_parser/formatter/data_tracer.py ---