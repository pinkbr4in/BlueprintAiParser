# --- START OF FILE blueprint_parser/parser.py ---

import re
from typing import List, Dict, Optional, Tuple, Any
import sys # For debug prints
# --- Use relative imports ---
from .nodes import (
    Node, Pin, create_node_instance, EdGraphNode_Comment,
    K2Node_CustomEvent, K2Node_Event, K2Node_EnhancedInputAction,
    K2Node_InputAxisEvent, K2Node_InputAction, K2Node_InputKey, K2Node_InputDebugKey,
    K2Node_InputAxisKeyEvent, K2Node_Timeline, K2Node_VariableSet, K2Node_VariableGet,
    K2Node_CallFunction, K2Node_CallParentFunction, K2Node_MacroInstance,
    K2Node_AddDelegate, K2Node_AssignDelegate, K2Node_RemoveDelegate, K2Node_ClearDelegate,
    K2Node_CallDelegate, K2Node_CreateDelegate, K2Node_MakeStruct, K2Node_BreakStruct,
    K2Node_SetFieldsInStruct, K2Node_SwitchEnum, K2Node_DynamicCast,
    K2Node_PromotableOperator, K2Node_CommutativeAssociativeBinaryOperator,
    K2Node_SpawnActorFromClass, K2Node_AddComponent, K2Node_CreateWidget,
    K2Node_CallArrayFunction, K2Node_GetClassDefaults, K2Node_GetSubsystem, K2Node_InputTouch,
    # --- Added Types ---
    K2Node_Literal, K2Node_ComponentBoundEvent, K2Node_ActorBoundEvent, K2Node_Composite
)
from .utils import (
    parse_properties_recursive,
    parse_properties,
    parse_pin_details,
    parse_linked_to,
    parse_variable_reference,
    extract_member_name,
    extract_simple_name_from_path,
    extract_specific_type,
    extract_macro_path, # Ensured import
    PROP_REGEX,
    VAR_REF_REGEX, STRUCT_TYPE_REGEX, ENUM_TYPE_REGEX, CAST_TARGET_TYPE_REGEX,
    DELEGATE_REF_REGEX, INPUT_AXIS_NAME_REGEX, INPUT_ACTION_NAME_REGEX,
    INPUT_KEY_NAME_REGEX,
    TIMELINE_NAME_REGEX, SUPER_FUNCTION_NAME_REGEX, INPUT_ACTION_PATH_REGEX,
    MACRO_PATH_REGEX, FUNCTION_REF_REGEX, CLASS_PATH_REGEX, MEMBER_NAME_REGEX # Added MEMBER_NAME_REGEX
)

# --- Debug Flag ---
ENABLE_PARSER_DEBUG = False # Set to True for verbose parser output


class BlueprintParser:
    def __init__(self):
        self.nodes: Dict[str, Node] = {} # Node GUID -> Node object
        self.name_to_guid_map: Dict[str, str] = {} # Node Name -> Node GUID
        # !!! REMOVED pins_by_id - It's unreliable due to non-unique Pin IDs !!!
        self.comments: Dict[str, EdGraphNode_Comment] = {} # Comment GUID -> Comment Node
        self.ue_version_major = 5 # Assume 5+ by default
        self.ue_version_minor = 0
        self.stats = {
            "total_nodes": 0,
            "total_pins": 0,
            "total_links_found": 0, # Raw links parsed
            "links_resolved": 0, # Links successfully connected
            "links_unresolved": 0, # Total unresolved (details below)
            "unresolved_name_lookups": 0, # Target node name/guid not found
            "unresolved_pin_lookups": 0, # Target node found, but pin ID not found *on that node*
            "missing_nodes": 0, # Target node GUID was in map, but node missing from dict
            "node_types": {},
            "pin_categories": {},
            "comment_count": 0,
        }

    def get_node_by_guid(self, guid: str) -> Optional[Node]:
        return self.nodes.get(guid)

    def parse(self, text: str) -> Dict[str, Node]:
        """Parses the input blueprint text into a dictionary of Node objects."""
        if ENABLE_PARSER_DEBUG: print("Starting Parse Pass 1: Object Creation...", file=sys.stderr)
        self._reset_state()
        self._detect_version(text)

        current_object_data = None
        line_num = 0
        object_stack = []

        for line in text.strip().splitlines():
            line_num += 1
            stripped_line = line.strip()
            if not stripped_line: continue

            if stripped_line.startswith("Begin Object"):
                properties = parse_properties(stripped_line, PROP_REGEX)
                temp_guid = properties.get("Name") or f"TEMP_{line_num}"
                current_object_data = {
                    "line_num": line_num, "begin_line": stripped_line,
                    "class_path": properties.get("Class"), "name": properties.get("Name"),
                    "property_lines": [], "temp_guid": temp_guid
                }
                object_stack.append(current_object_data)
                # if ENABLE_PARSER_DEBUG: print(f"DEBUG: Begin Object. Name='{current_object_data['name']}', TempGUID='{temp_guid}'", file=sys.stderr)

            elif stripped_line.startswith("End Object"):
                if not object_stack:
                    if ENABLE_PARSER_DEBUG: print(f"Warning: Line {line_num}: Found 'End Object' without matching 'Begin'.", file=sys.stderr)
                    continue
                completed_object_data = object_stack.pop()
                self._process_and_finalize_node(completed_object_data)

            elif object_stack:
                object_stack[-1]["property_lines"].append(stripped_line)

        if object_stack:
            if ENABLE_PARSER_DEBUG: print(f"Warning: Reached end of file with {len(object_stack)} unclosed Object block(s). Processing remaining.", file=sys.stderr)
            while object_stack:
                completed_object_data = object_stack.pop()
                self._process_and_finalize_node(completed_object_data)

        # Calculate total pins *after* processing all nodes
        self.stats["total_pins"] = sum(len(n.pins) for n in self.nodes.values()) + sum(len(c.pins) for c in self.comments.values())

        if ENABLE_PARSER_DEBUG: print(f"Parse Pass 1 complete. Found {self.stats['total_nodes']} nodes ({len(self.comments)} comments), {self.stats['total_pins']} pins.", file=sys.stderr)

        self._resolve_links() # Resolve links after all nodes/pins finalized
        if ENABLE_PARSER_DEBUG: print("Parsing finished.", file=sys.stderr)
        return self.nodes

    def _reset_state(self):
        self.nodes = {}
        self.name_to_guid_map = {}
        # No central pin map to reset
        self.comments = {}
        self.stats = {k: 0 if isinstance(v, int) else {} for k, v in self.stats.items()}

    def _detect_version(self, text: str):
        # Basic heuristic, can be refined
        if '"NodeGuid"=' in text or '"NodeComment"=' in text:
            self.ue_version_major = 5
            self.ue_version_minor = 2 # Assumed, >= 5.2 typically uses quoted keys
            if ENABLE_PARSER_DEBUG: print("DEBUG: Detected UE version likely >= 5.2 (quoted keys)")
        elif 'NodeGuid=' in text:
            self.ue_version_major = 4 # Or maybe 5.0/5.1
            self.ue_version_minor = 27 # Placeholder
            if ENABLE_PARSER_DEBUG: print("DEBUG: Detected UE version likely < 5.2 (unquoted keys)")
        else:
             if ENABLE_PARSER_DEBUG: print("DEBUG: Could not reliably detect UE version, assuming 5.0+")


    def _process_and_finalize_node(self, node_data: Dict[str, Any]):
        class_path = node_data["class_path"]
        name = node_data["name"]
        temp_guid_used_for_creation = node_data["temp_guid"]
        property_lines = node_data["property_lines"]
        begin_line = node_data["begin_line"]
        line_num = node_data["line_num"]

        if not class_path or not name:
            missing = "Class" if not class_path else "Name"
            if ENABLE_PARSER_DEBUG: print(f"Warning: Skipping object at line {line_num} due to missing {missing}: {begin_line}", file=sys.stderr)
            return

        new_node = create_node_instance(temp_guid_used_for_creation, class_path)
        new_node.name = name
        new_node.raw_properties.update(parse_properties(begin_line, PROP_REGEX))

        for line in property_lines:
            self._handle_property_line(line, new_node)

        node_guid_prop = new_node.raw_properties.get("NodeGuid")
        final_guid = str(node_guid_prop).strip().strip('"') if node_guid_prop else name

        new_node.guid = final_guid

        # Update node_guid for all pins belonging to this node
        for pin in new_node.pins.values():
            if pin.node_guid != final_guid:
                pin.node_guid = final_guid

        is_comment = isinstance(new_node, EdGraphNode_Comment)
        if final_guid in self.nodes and not is_comment:
            if ENABLE_PARSER_DEBUG: print(f"Warning: Duplicate NodeGUID '{final_guid}'. Overwriting node '{self.nodes[final_guid].name}'.", file=sys.stderr)
        if name in self.name_to_guid_map and self.name_to_guid_map[name] != final_guid:
            if not is_comment and not isinstance(self.nodes.get(self.name_to_guid_map.get(name)), EdGraphNode_Comment):
                if ENABLE_PARSER_DEBUG: print(f"Warning: Duplicate node name '{name}'. Mapping points to latest GUID '{final_guid}'.", file=sys.stderr)

        if is_comment:
            self.comments[final_guid] = new_node
            self.stats["comment_count"] += 1
        else:
            self.nodes[final_guid] = new_node
            self.name_to_guid_map[name] = final_guid

        self.stats["total_nodes"] += 1
        node_type_key = new_node.node_type
        self.stats["node_types"][node_type_key] = self.stats["node_types"].get(node_type_key, 0) + 1

        # Update pin category stats and raw link count
        for pin in new_node.pins.values():
            if pin.category:
                cat_key = pin.category or "Unknown"
                self.stats["pin_categories"][cat_key] = self.stats["pin_categories"].get(cat_key, 0) + 1
            self.stats["total_links_found"] += len(pin.linked_to_guids)

        try:
            self._finalize_node_properties(new_node, property_lines)
        except Exception as e:
            import traceback
            print(f"ERROR: Failed to finalize properties for node {final_guid} ({new_node.name}): {e}", file=sys.stderr)
            if ENABLE_PARSER_DEBUG: traceback.print_exc()

    def _handle_property_line(self, line: str, node: Node):
        line = line.strip()
        if not line: return

        if line.startswith("CustomProperties Pin"):
            match = re.match(r'CustomProperties\s+Pin\s*\((.*)\)', line, re.IGNORECASE | re.DOTALL)
            if match:
                pin_content = match.group(1).strip()
                try:
                    pin_details = parse_pin_details(pin_content)
                    pin_id = pin_details.get("PinId")
                    if pin_id:
                        pin = node.pins.get(pin_id)
                        if not pin:
                            pin = Pin(str(pin_id), node.guid) # Assign node_guid during creation
                            node.pins[pin_id] = pin

                        pin.raw_properties.update(pin_details)
                        pin.name = str(pin_details.get("PinName","")).strip('"') or pin.name
                        fn_val = pin_details.get("PinFriendlyName")
                        friendly_name_str = None
                        if isinstance(fn_val, dict): friendly_name_str = str(fn_val.get("SourceString") or fn_val.get("_value_2") or fn_val)
                        elif fn_val: friendly_name_str = str(fn_val).strip('"')
                        pin.friendly_name = friendly_name_str or pin.friendly_name

                        pin.direction = pin_details.get("Direction") or pin.direction
                        pin.category = pin_details.get("PinType.PinCategory") or pin.category
                        pin.sub_category = pin_details.get("PinType.PinSubCategory") or pin.sub_category
                        pin.sub_category_object = pin_details.get("PinType.PinSubCategoryObject") or pin.sub_category_object
                        pin.container_type = pin_details.get("PinType.ContainerType") or pin_details.get("PinType_0_ContainerType") or pin.container_type

                        is_ref = pin_details.get("PinType.bIsReference", pin.is_reference)
                        pin.is_reference = str(is_ref).lower() == 'true' if isinstance(is_ref, str) else bool(is_ref)
                        is_const = pin_details.get("PinType.bIsConst", pin.is_const)
                        pin.is_const = str(is_const).lower() == 'true' if isinstance(is_const, str) else bool(is_const)

                        if "DefaultValue" in pin_details: pin.default_value = str(pin_details["DefaultValue"])
                        elif "DefaultTextValue" in pin_details: pin.default_value = str(pin_details["DefaultTextValue"])
                        if "DefaultObject" in pin_details: pin.default_object = str(pin_details["DefaultObject"]).strip('"')
                        if "DefaultStruct" in pin_details: pin.default_struct = pin_details["DefaultStruct"]
                        if "AutogeneratedDefaultValue" in pin_details: pin.autogenerated_default_value = str(pin_details["AutogeneratedDefaultValue"])

                        # Store raw links - these will be resolved later
                        pin.linked_to_guids.extend(pin_details.get("LinkedTo", []))
                        # Remove duplicates
                        pin.linked_to_guids = list(dict.fromkeys(pin.linked_to_guids))

                    else:
                        if ENABLE_PARSER_DEBUG: print(f"Warning: Pin definition missing PinId in node {node.name}: {line[:100]}...", file=sys.stderr)
                except Exception as e:
                    import traceback
                    print(f"Error parsing Pin content for node {node.name}: {e}\nContent: {pin_content[:100]}...", file=sys.stderr)
                    if ENABLE_PARSER_DEBUG: traceback.print_exc()
            else:
                if ENABLE_PARSER_DEBUG: print(f"Warning: Could not parse CustomProperties Pin line structure: {line[:100]}...", file=sys.stderr)
        else:
            try:
                properties = parse_properties_recursive(line)
                if properties:
                    for key, value in properties.items():
                        if isinstance(value, str):
                            if value.lower() == 'true': value = True
                            elif value.lower() == 'false': value = False
                        node.raw_properties[key] = value
                elif line and '=' not in line and not line.startswith(('/', '#', '"', '(', ')', '<', '>')):
                    # Handle simple boolean flags like bCanEverTick
                    if line.startswith(('b', 'bCan', 'bHas', 'bIs')):
                         node.raw_properties[line.strip()] = True
            except Exception as e:
                import traceback
                print(f"Error processing property line for node {node.name}: {e}\nLine: {line}", file=sys.stderr)
                if ENABLE_PARSER_DEBUG: traceback.print_exc()

    def _finalize_node_properties(self, node: Node, property_lines: List[str]):
        full_property_text = "\n".join(property_lines) # For regex fallbacks
        pos_x = node.raw_properties.get('NodePosX')
        pos_y = node.raw_properties.get('NodePosY')
        node.position = (int(float(pos_x or 0)), int(float(pos_y or 0)))
        node_comment = node.raw_properties.get('NodeComment')
        if isinstance(node_comment, str):
            try:
                # Handle potential escape sequences in comments
                cleaned_comment = node_comment.strip('"').replace('\\"', '"').replace("\\'", "'").replace('\\n', '\n').replace('\\\\', '\\')
                node.node_comment = cleaned_comment
            except Exception: node.node_comment = node_comment # Fallback if complex parsing fails
        else: node.node_comment = str(node_comment) if node_comment is not None else None

        if isinstance(node, EdGraphNode_Comment):
            node.comment_text = node.node_comment
            node.comment_color = str(node.raw_properties.get("CommentColor")) # Store as string '(<R>,<G>,<B>,<A>)'
            node.NodeWidth = int(float(node.raw_properties.get("NodeWidth", 500)))
            node.NodeHeight = int(float(node.raw_properties.get("NodeHeight", 300)))
        elif isinstance(node, K2Node_CustomEvent):
            node.custom_function_name = str(node.raw_properties.get("CustomFunctionName", "")).strip('"') or None
        # --- NEW: K2Node_Literal ---
        elif isinstance(node, K2Node_Literal):
             # Usually doesn't have extra properties, relies on pins' DefaultValue
             pass # No specific props needed for now
        # --- END NEW ---
        elif isinstance(node, K2Node_Event):
            ref = node.raw_properties.get("EventReference") or node.raw_properties.get("FunctionReference")
            node.event_function_name = extract_member_name(ref)
        # --- NEW: K2Node_ComponentBoundEvent ---
        elif isinstance(node, K2Node_ComponentBoundEvent):
            node.component_property_name = str(node.raw_properties.get("ComponentPropertyName", "")).strip('"') or None
            node.delegate_property_name = str(node.raw_properties.get("DelegatePropertyName", "")).strip('"') or None
            owner_class_ref = node.raw_properties.get("DelegateOwnerClass")
            node.delegate_owner_class = str(owner_class_ref).strip("'\"") if owner_class_ref else None
        # --- NEW: K2Node_ActorBoundEvent ---
        elif isinstance(node, K2Node_ActorBoundEvent):
            node.delegate_property_name = str(node.raw_properties.get("DelegatePropertyName", "")).strip('"') or None
            # Actor ref ('EventOwner') might be harder to parse reliably from text, skip for now
        # --- END NEW ---
        elif isinstance(node, K2Node_EnhancedInputAction):
            action_ref = node.raw_properties.get("InputAction")
            action_path = str(action_ref).strip("'\"") if action_ref else extract_specific_type(full_property_text, INPUT_ACTION_PATH_REGEX, 1)
            node.input_action_path = action_path
            node.input_action_name = extract_simple_name_from_path(node.input_action_path)
        elif isinstance(node, K2Node_InputAxisEvent):
            node.axis_name = str(node.raw_properties.get("InputAxisName", "")).strip('"') or extract_specific_type(full_property_text, INPUT_AXIS_NAME_REGEX)
        elif isinstance(node, K2Node_InputAction):
            node.action_name = str(node.raw_properties.get("InputActionName", "")).strip('"') or extract_specific_type(full_property_text, INPUT_ACTION_NAME_REGEX)
        elif isinstance(node, K2Node_InputKey) or isinstance(node, K2Node_InputDebugKey):
            node.input_key_name = extract_simple_name_from_path(node.raw_properties.get("InputKey")) or extract_specific_type(full_property_text, INPUT_KEY_NAME_REGEX)
        elif isinstance(node, K2Node_InputTouch): pass # No specific properties needed currently
        elif isinstance(node, K2Node_InputAxisKeyEvent):
            node.axis_key_name = extract_simple_name_from_path(node.raw_properties.get("AxisKey")) or extract_specific_type(full_property_text, INPUT_KEY_NAME_REGEX)
        elif isinstance(node, K2Node_Timeline):
            node.timeline_name = str(node.raw_properties.get("TimelineName", "")).strip('"') or extract_specific_type(full_property_text, TIMELINE_NAME_REGEX)
        elif isinstance(node, K2Node_VariableSet) or isinstance(node, K2Node_VariableGet):
            var_ref = node.raw_properties.get("VariableReference")
            node.variable_name = parse_variable_reference(var_ref)
            pin = node.get_value_output_pin() if isinstance(node, K2Node_VariableGet) else node.get_value_input_pin()
            if pin: node.variable_type = pin.get_type_signature()
        elif isinstance(node, K2Node_CallFunction):
            func_ref = node.raw_properties.get("FunctionReference")
            node.function_name = extract_member_name(func_ref) or extract_specific_type(full_property_text, MEMBER_NAME_REGEX, 1) # Using updated constant
            is_pure = node.raw_properties.get("bIsPureFunc", node.raw_properties.get("bDefaultsToPureFunc", False))
            node.is_pure_call = str(is_pure).lower() == 'true' if isinstance(is_pure, str) else bool(is_pure)
            is_latent = node.raw_properties.get("bIsLatent", False)
            node.is_latent = str(is_latent).lower() == 'true' if isinstance(is_latent, str) else bool(is_latent)
            # Backup check for LatentInfo pin
            if not node.is_latent: node.is_latent = any(p.name == "LatentInfo" for p in node.pins.values())
        elif isinstance(node, K2Node_CallParentFunction):
            super_name = node.raw_properties.get("SuperFunctionName") or extract_member_name(node.raw_properties.get("FunctionReference")) or extract_specific_type(full_property_text, SUPER_FUNCTION_NAME_REGEX)
            node.parent_function_name = str(super_name).strip('"') if super_name else None
        elif isinstance(node, K2Node_MacroInstance):
            macro_ref = node.raw_properties.get("MacroGraphReference")
            node.macro_graph_path = extract_macro_path(macro_ref)
            node.macro_type = extract_simple_name_from_path(node.macro_graph_path) or "Unknown"
            # Refine detection of standard macros
            known_macro_names = {"FlipFlop", "Gate", "IsValid", "ForEachLoop", "ForEachLoopWithBreak", "ForLoop", "ForLoopWithBreak", "WhileLoop", "DoN", "DoOnce", "MultiGate"}
            if node.macro_type not in known_macro_names:
                path_lower = (node.macro_graph_path or "").lower()
                for name in known_macro_names:
                     if name.lower() in path_lower: node.macro_type = name; break
            node.is_pure_call = not any(p.is_execution() for p in node.pins.values())
        elif isinstance(node, (K2Node_AddDelegate, K2Node_AssignDelegate, K2Node_RemoveDelegate, K2Node_ClearDelegate, K2Node_CallDelegate)):
            delegate_ref = node.raw_properties.get("DelegateReference")
            node.delegate_name = extract_member_name(delegate_ref)
        elif isinstance(node, K2Node_CreateDelegate):
            node.function_name = str(node.raw_properties.get("FunctionName", "")).strip('"') or None
            delegate_pin = node.get_delegate_output_pin()
            if delegate_pin: node.delegate_name = delegate_pin.name
        elif isinstance(node, (K2Node_MakeStruct, K2Node_BreakStruct, K2Node_SetFieldsInStruct)):
            struct_type_prop = node.raw_properties.get("StructType")
            # --- Debug Print Start ---
            if ENABLE_PARSER_DEBUG and isinstance(node, K2Node_MakeStruct):
                 print(f"DEBUG [MakeStruct Finalize]: Raw StructType Prop: {struct_type_prop}", file=sys.stderr)
            # --- Debug Print End ---
            node.struct_type = extract_simple_name_from_path(struct_type_prop)
            # --- Debug Print Start ---
            if ENABLE_PARSER_DEBUG and isinstance(node, K2Node_MakeStruct):
                 print(f"DEBUG [MakeStruct Finalize]: Extracted Simple Name: {node.struct_type}", file=sys.stderr)
            # --- Debug Print End ---
            # Fallback logic
            if not node.struct_type: node.struct_type = extract_simple_name_from_path(extract_specific_type(full_property_text, STRUCT_TYPE_REGEX, 1))
            if not node.struct_type:
                pin = node.get_output_struct_pin() if isinstance(node, K2Node_MakeStruct) else node.get_input_struct_pin()
                if pin and pin.sub_category_object: node.struct_type = extract_simple_name_from_path(pin.sub_category_object)
        elif isinstance(node, K2Node_SwitchEnum):
            enum_ref = node.raw_properties.get("Enum")
            node.enum_type = extract_simple_name_from_path(enum_ref) or extract_specific_type(full_property_text, ENUM_TYPE_REGEX, 1)
            if not node.enum_type:
                sel_pin = node.get_selection_pin()
                if sel_pin and sel_pin.sub_category_object: node.enum_type = extract_simple_name_from_path(sel_pin.sub_category_object)
        elif isinstance(node, K2Node_DynamicCast):
            target_ref = node.raw_properties.get("TargetType")
            node.target_type = extract_simple_name_from_path(target_ref) or extract_specific_type(full_property_text, CAST_TARGET_TYPE_REGEX, 1)
            if not node.target_type:
                as_pin = node.get_as_pin()
                if as_pin and as_pin.sub_category_object: node.target_type = extract_simple_name_from_path(as_pin.sub_category_object)
        elif isinstance(node, (K2Node_PromotableOperator, K2Node_CommutativeAssociativeBinaryOperator)):
            func_ref = node.raw_properties.get("FunctionReference")
            # Use existing MemberName extraction
            op_name = extract_member_name(func_ref) or str(node.raw_properties.get("OperationName", "")).strip('"') or None
            # Store the base operation name (e.g., "Add" from "Add_IntInt")
            if op_name and '_' in op_name:
                base_op_name = op_name.split('_')[0]
                # Handle specific cases like EqualEqual
                if base_op_name == "EqualEqual": base_op_name = "EqualEqual"
                elif base_op_name == "NotEqual": base_op_name = "NotEqual"
                # Store the cleaned name
                node.operation_name = base_op_name
            else:
                node.operation_name = op_name
            node.function_name = node.operation_name # Also store for consistency if needed elsewhere
        elif isinstance(node, K2Node_SpawnActorFromClass):
            class_ref = node.raw_properties.get("ClassToSpawn")
            node.spawn_class_path = str(class_ref).strip("'\"") if class_ref else extract_specific_type(full_property_text, CLASS_PATH_REGEX, 2, "ClassToSpawn")
        elif isinstance(node, K2Node_AddComponent):
            class_ref = node.raw_properties.get("ComponentClass")
            node.component_class_path = str(class_ref).strip("'\"") if class_ref else extract_specific_type(full_property_text, CLASS_PATH_REGEX, 2, "ComponentClass")
            # Additional Fallbacks for AddComponent
            if not node.component_class_path:
                template_type = node.raw_properties.get("TemplateType") # Less common?
                if template_type: node.component_class_path = str(template_type)
            if not node.component_class_path:
                template_bp = node.raw_properties.get("TemplateBlueprint") # For BP component classes
                if template_bp: node.component_class_path = str(template_bp)
            if not node.component_class_path:
                class_pin = node.get_component_class_pin() # Check DefaultObject on the class pin
                if class_pin and class_pin.default_object: node.component_class_path = str(class_pin.default_object).strip("'\"")
        elif isinstance(node, K2Node_CreateWidget):
            class_ref = node.raw_properties.get("WidgetClass")
            node.widget_class_path = str(class_ref).strip("'\"") if class_ref else extract_specific_type(full_property_text, CLASS_PATH_REGEX, 2, "WidgetClass")
        # --- MODIFIED: K2Node_CallArrayFunction ---
        elif isinstance(node, K2Node_CallArrayFunction):
             func_ref = node.raw_properties.get("FunctionReference")
             # Extract and store the specific array function name
             node.array_function_name = extract_member_name(func_ref) or extract_specific_type(full_property_text, MEMBER_NAME_REGEX, 1)
        # --- END MODIFICATION ---
        elif isinstance(node, K2Node_GetClassDefaults):
            # Try getting class from ShowPinForProperties first
            class_prop = node.raw_properties.get("ShowPinForProperties")
            node.target_class_path = None
            if isinstance(class_prop, list) and class_prop and isinstance(class_prop[0], dict):
                node.target_class_path = str(class_prop[0].get("PropertyClass")).strip("'\"") or None
            # Fallback: check the first non-self output pin's subcategory object
            if not node.target_class_path:
                output_pin = next((p for p in node.get_output_pins() if p.name != 'self'), None)
                if output_pin and output_pin.sub_category_object: node.target_class_path = str(output_pin.sub_category_object).strip("'\"")
        elif isinstance(node, K2Node_GetSubsystem):
            # Correctly look for "CustomClass" property
            class_ref = node.raw_properties.get("CustomClass")
            # --- Debug Print ---
            if ENABLE_PARSER_DEBUG: print(f"DEBUG [GetSubsystem Finalize]: Found CustomClass Prop: {class_ref}", file=sys.stderr)
            # --- End Debug ---
            node.subsystem_class_path = str(class_ref).strip("'\"") if class_ref else None
            # Removed fallback using CLASS_PATH_REGEX as it's less reliable for CustomClass
            # --- Debug Print ---
            if ENABLE_PARSER_DEBUG: print(f"DEBUG [GetSubsystem Finalize]: Set subsystem_class_path: {node.subsystem_class_path}", file=sys.stderr)
            # --- End Debug ---
        # --- NEW: K2Node_Composite ---
        elif isinstance(node, K2Node_Composite):
            bound_graph_ref = node.raw_properties.get("BoundGraph")
            # Use macro path extractor logic as it often holds the graph path/name
            graph_path = extract_macro_path(bound_graph_ref)
            node.bound_graph_name = extract_simple_name_from_path(graph_path) or "CollapsedGraph"
        # --- END NEW ---

    # --- CORRECTED _resolve_links ---
    def _resolve_links(self):
        """Iterate through all parsed nodes and pins to connect Pin objects."""
        resolved_links = 0
        unresolved_name_lookups = 0
        unresolved_pin_lookups = 0
        unresolved_missing_nodes = 0
        total_potential_links = self.stats.get("total_links_found", 0)

        if ENABLE_PARSER_DEBUG: print(f"\n--- Starting Link Resolution (Pass 2) ---", file=sys.stderr)
        if ENABLE_PARSER_DEBUG: print(f"DEBUG: Potential links to resolve: {total_potential_links}", file=sys.stderr)
        if ENABLE_PARSER_DEBUG: print(f"DEBUG: Nodes available: {len(self.nodes)}, Comments: {len(self.comments)}", file=sys.stderr)

        # Iterate through a copy of items to avoid issues if nodes were modified (shouldn't happen here)
        all_nodes_to_process = list(self.nodes.items()) + list(self.comments.items())

        for node_guid, node in all_nodes_to_process:
            for pin_id, pin in list(node.pins.items()):
                # Reset actual links for this run
                pin.linked_pins = []
                pin.source_pin_for = []

                if not pin.linked_to_guids: continue

                # if ENABLE_PARSER_DEBUG: print(f"\n   Node '{node.name}' ({node_guid[:8]}): Pin '{pin.name}' ({pin_id})", file=sys.stderr)

                for target_link_info in pin.linked_to_guids:
                    # Ensure target_link_info is a tuple (NodeRef, PinID)
                    if not isinstance(target_link_info, (list, tuple)) or len(target_link_info) != 2:
                        if ENABLE_PARSER_DEBUG: print(f"     WARNING: Malformed link info in pin {pin_id} of node {node_guid}: {target_link_info}. Skipping.", file=sys.stderr)
                        continue

                    target_node_ref, target_pin_id_ref = target_link_info
                    # if ENABLE_PARSER_DEBUG: print(f"     Attempting link to: Node Ref='{target_node_ref}', Pin Ref='{target_pin_id_ref}'", file=sys.stderr)

                    target_node: Optional[Node] = None
                    actual_target_guid: Optional[str] = None

                    # Try resolving by Name first (more common in links)
                    resolved_guid_from_name = self.name_to_guid_map.get(target_node_ref)
                    if resolved_guid_from_name:
                        actual_target_guid = resolved_guid_from_name
                        target_node = self.nodes.get(actual_target_guid) or self.comments.get(actual_target_guid) # Check both nodes and comments
                        # if ENABLE_PARSER_DEBUG: print(f"        Node Ref '{target_node_ref}' found in name map -> GUID '{actual_target_guid}'. Node/Comment object found: {target_node is not None}", file=sys.stderr)
                    else:
                        # If not found by name, assume the ref *is* the GUID
                        actual_target_guid = target_node_ref
                        target_node = self.nodes.get(actual_target_guid) or self.comments.get(actual_target_guid) # Check both nodes and comments
                        # if ENABLE_PARSER_DEBUG: print(f"        Node Ref '{target_node_ref}' not in name map. Treating as GUID. Node/Comment object found: {target_node is not None}", file=sys.stderr)

                    if target_node:
                        target_pin = target_node.pins.get(target_pin_id_ref)

                        if target_pin:
                            # if ENABLE_PARSER_DEBUG: print(f"        Target Pin FOUND: '{target_pin.name}' ({target_pin_id_ref}) within Node/Comment '{target_node.name}'. SUCCESS.", file=sys.stderr)
                            if target_pin not in pin.linked_pins:
                                pin.linked_pins.append(target_pin)
                            # Add back-reference
                            if pin not in target_pin.source_pin_for:
                                target_pin.source_pin_for.append(pin)
                                # if ENABLE_PARSER_DEBUG: print(f"          Appended source link to target pin '{target_pin.name}'. New source_pin_for count: {len(target_pin.source_pin_for)}", file=sys.stderr)
                            resolved_links += 1
                        else:
                            unresolved_pin_lookups += 1
                            if ENABLE_PARSER_DEBUG:
                                print(f"        Target Pin ID '{target_pin_id_ref}' NOT FOUND within pins of target node/comment '{target_node.name}' ({target_node.guid[:8]}). LOOKUP FAILURE.", file=sys.stderr)
                                target_pin_ids_on_node = list(target_node.pins.keys())
                                print(f"          Available Pin IDs on target: {target_pin_ids_on_node}", file=sys.stderr)
                    else:
                        unresolved_name_lookups += 1
                        if ENABLE_PARSER_DEBUG: print(f"        Target Node/Comment NOT FOUND using ref '{target_node_ref}' (resolved/tried GUID: '{actual_target_guid}'). NAME/GUID LOOKUP FAILURE.", file=sys.stderr)
                        # Check if name lookup succeeded but the node object itself is missing (should be rare)
                        if resolved_guid_from_name and resolved_guid_from_name not in self.nodes and resolved_guid_from_name not in self.comments:
                                unresolved_missing_nodes += 1
                                if ENABLE_PARSER_DEBUG: print(f"          (Name lookup succeeded, but node/comment object missing from dictionaries)", file=sys.stderr)


        self.stats["links_resolved"] = resolved_links
        # Calculate total unresolved links (initial count minus successfully resolved ones)
        self.stats["links_unresolved"] = total_potential_links - resolved_links
        self.stats["unresolved_name_lookups"] = unresolved_name_lookups
        self.stats["unresolved_pin_lookups"] = unresolved_pin_lookups
        self.stats["missing_nodes"] = unresolved_missing_nodes

        if ENABLE_PARSER_DEBUG:
            print(f"\n--- Link Resolution Finished ---", file=sys.stderr)
            print(f"DEBUG: Links Found (Raw): {total_potential_links}", file=sys.stderr)
            print(f"DEBUG: Links Resolved: {resolved_links}", file=sys.stderr)
            print(f"DEBUG: Links Unresolved: {self.stats['links_unresolved']}", file=sys.stderr)
            if self.stats['links_unresolved'] > 0:
                print(f"   Unresolved Breakdown: Name/GUID Lookups Failed={unresolved_name_lookups}, Pin Lookups Failed={unresolved_pin_lookups}, Nodes Missing After Name Lookup={unresolved_missing_nodes}", file=sys.stderr)
        if ENABLE_PARSER_DEBUG: print(f"----------------------------------\n", file=sys.stderr)


# --- END OF FILE blueprint_parser/parser.py ---