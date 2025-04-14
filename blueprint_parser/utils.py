# --- START OF FILE blueprint_parser/utils.py ---

# blueprint_parser/utils.py
import re
from typing import Dict, Any, List, Tuple, Optional, Union

# Regex for simple Key=Value or Key=(...) or Key="Value" pairs on property lines
# Allows . / ' - _ in keys and values. Added A-Fa-f for GUIDs/Hex.
# Handles optional double quotes around the key for UE5.2+
# Improved to better handle nested () and quoted values within ()
PROP_REGEX = re.compile(r'("?[a-zA-Z0-9_.]+"?)\s*=\s*(".*?"|\(.*\)|(?:/Script/CoreUObject\.)?(?:Class|ScriptStruct|Enum)\'[^\']+\'|[a-zA-Z0-9_./\'":A-Fa-f-]+)')


# Regex specifically for parsing the contents within Pin (...)
PIN_PROP_REGEX = re.compile(r'([a-zA-Z0-9_.]+)\s*=\s*')

# Regex for VariableReference MemberName
VAR_REF_REGEX = re.compile(r'MemberName="([^"]+)"')
# Regex for FunctionReference (captures the whole reference string inside parens)
FUNCTION_REF_REGEX = re.compile(r'FunctionReference=\(([^)]+)\)') # Capture content *inside* parens
# Regex for StructType in Make/Break nodes (handles optional path prefixes and quotes)
STRUCT_TYPE_REGEX = re.compile(r'StructType=(?:/Script/CoreUObject\.ScriptStruct|Class)?\'?\"?([^ \'\"]+)\'?\"?')
# Regex for Enum Type (handles optional path prefixes and quotes)
ENUM_TYPE_REGEX = re.compile(r'Enum=(?:/Script/CoreUObject\.Enum|Class)?\'?\"?([^ \'\"]+)\'?\"?')
# Regex for TargetType in Cast nodes (handles optional path prefixes and quotes)
CAST_TARGET_TYPE_REGEX = re.compile(r'TargetType=(?:/Script/CoreUObject\.Class)?\'?\"?([^ \'\"]+)\'?\"?')
# Regex for DelegateReference (captures the whole reference string inside parens)
DELEGATE_REF_REGEX = re.compile(r'DelegateReference=\(([^)]+)\)') # Capture content *inside* parens
# Regex for InputAxisName
INPUT_AXIS_NAME_REGEX = re.compile(r'InputAxisName="?([^"\s]+)"?')
# Regex for InputActionName (legacy)
INPUT_ACTION_NAME_REGEX = re.compile(r'InputActionName="?([^"\s]+)"?')
# Regex for InputKey name
INPUT_KEY_NAME_REGEX = re.compile(r'(?:InputKey|AxisKey)=Key\'([^\']+)\'')
# Regex for TimelineName
TIMELINE_NAME_REGEX = re.compile(r'TimelineName="?([^"\s]+)"?')
# Regex for SuperFunctionName in CallParentFunction
SUPER_FUNCTION_NAME_REGEX = re.compile(r'SuperFunctionName="?([^"\s]+)"?')
# Regex for InputAction path (Enhanced Input)
INPUT_ACTION_PATH_REGEX = re.compile(r'InputAction=(?:\/Script\/EnhancedInput\.InputAction)?\'?\"?([^ \'\"]+)\'?\"?')
# Regex for MacroGraph paths
MACRO_PATH_REGEX = re.compile(r'(?:MacroGraph|AssetPtr|ObjectPath|Graph)\s*=\s*(?:\/Script\/Engine\.EdGraph)?\'?\"?([^ \'\"]+)\'?\"?')
# Regex for Class paths (e.g., ClassToSpawn, WidgetClass)
CLASS_PATH_REGEX = re.compile(r'([a-zA-Z0-9_]+Class)=(?:/Script/CoreUObject\.Class)?\'?\"?([^ \'\"]+)\'?\"?')


# Regex for Function/Delegate MemberName
MEMBER_NAME_REGEX = re.compile(r'MemberName="([^"]+)"')
# Regex for extracting simple class/struct/enum names from paths
CLEAN_NAME_REGEX = re.compile(r"[./']([^./']+)$")
# Regex for NodeName PinID pairs within LinkedTo=(...) (Handles quotes around NodeName)
# Updated to be more robust against complex node names
# V3: More flexible Node Ref capture (quoted or unquoted word/path/guid) + Pin ID
LINKED_TO_PAIR_REGEX = re.compile(r'("?[\w./\':-]+"?)?\s+([a-zA-Z0-9_-]+)')


def parse_properties(line: str, regex: re.Pattern) -> Dict[str, str]:
    """Parses a line into key-value pairs using the provided regex. Returns strings."""
    properties = {}
    # Simple parsing for the Begin Object line - primarily for Class and Name
    match_class = re.search(r'Class=([^\s\'"]+)', line) # Avoid capturing quotes
    match_name = re.search(r'Name="([^"]+)"', line) # Assume Name is quoted
    if match_class:
        properties["Class"] = match_class.group(1).strip().strip("'")
    if match_name:
        properties["Name"] = match_name.group(1).strip()
    # Add other simple direct properties if needed, but most are handled recursively
    return properties


def parse_value(value_str: str) -> Any:
    """Recursively parses complex values like (...) containing key=value pairs or lists."""
    value_str = value_str.strip()

    # Handle Objects/Structs/Lists in Parentheses (...)
    if value_str.startswith('(') and value_str.endswith(')'):
        content = value_str[1:-1].strip()
        if not content:
            return {} # Empty parentheses like PinType.PinSubCategoryMemberReference=()

        # Enhanced Parsing Logic for Parenthesized Content
        items = []
        buffer = ""
        paren_level = 0
        in_quotes = False
        escaped = False
        is_dict_like = False # Assume list/tuple unless '=' found at level 0
        first_equals_found_at_level_0 = False

        # First pass to check structure and split correctly
        split_indices = [-1] # Start index for first item
        for i, char in enumerate(content):
            if char == '\\' and not escaped:
                escaped = True
                buffer += char
                continue
            if char == '"' and not escaped:
                in_quotes = not in_quotes
            elif not in_quotes:
                if char == '(':
                    paren_level += 1
                elif char == ')':
                    paren_level -= 1
                elif char == '=' and paren_level == 0:
                    # Found '=' at the top level, likely a dictionary
                    is_dict_like = True
                    if not first_equals_found_at_level_0:
                        # Check if it's a key=value pair format
                        key_candidate = buffer.strip().strip('"')
                        if re.match(r'^[a-zA-Z_][a-zA-Z0-9_.]*$', key_candidate) or re.match(r'^[XYZRPYGAxyzrpyga]$', key_candidate):
                           first_equals_found_at_level_0 = True
                        buffer = "" # Reset buffer after finding equals
                        # Don't split here, let comma handle splitting pairs
                    else:
                         buffer += char # Part of a value
                elif char == ',' and paren_level == 0:
                    # Found a separator at the top level
                    split_indices.append(i)
                    buffer = "" # Reset buffer for next segment
                    continue # Move to next character

            buffer += char
            escaped = False

        split_indices.append(len(content)) # End index for last item

        # Now, process the segments
        segments = []
        for j in range(len(split_indices) - 1):
            start = split_indices[j] + 1
            end = split_indices[j+1]
            segments.append(content[start:end].strip())

        # Decide how to parse based on structure
        if is_dict_like and first_equals_found_at_level_0:
            # Parse as dictionary
            parsed_dict = {}
            for segment in segments:
                match = re.match(r'\s*("?[a-zA-Z0-9_.]+"?)\s*=\s*(.*)\s*', segment)
                if match:
                    key = match.group(1).strip().strip('"')
                    raw_value = match.group(2).strip()
                    parsed_dict[key] = parse_value(raw_value)
                elif segment: # Handle potential values without explicit keys if format is mixed/weird
                    parsed_dict[f"_value_{len(parsed_dict)}"] = parse_value(segment)
            return parsed_dict
        else:
            # Parse as list/tuple
            parsed_items = [parse_value(segment) for segment in segments if segment] # Avoid parsing empty segments
            # If only one item and no comma was actually present at level 0, return the item directly
            if len(parsed_items) == 1 and ',' not in content: # Simplified check
                return parsed_items[0]
            return parsed_items


    # Handle Quoted Strings ""
    elif value_str.startswith('"') and value_str.endswith('"'):
        val = value_str[1:-1]
        # Basic unescaping for \", \', \\, \n, \r
        return val.replace(r'\"', r'"').replace(r"\'", r"'").replace(r'\\n', '\n').replace(r'\\r', '').replace(r'\\', '\\')

    # Handle Path Names like Class'/Script/...' or Object'/Game/...' or Enum'/Script/...'
    elif re.match(r"^(?:Class|Object|Enum|ScriptStruct|UserDefinedEnum|UserDefinedStruct)'", value_str) and value_str.endswith('\''):
       return value_str # Keep full path string

    # Handle Booleans
    elif value_str.lower() == 'true': return True
    elif value_str.lower() == 'false': return False

    # Handle None
    elif value_str.lower() == 'none': return None

    # Handle Numbers (Int/Float)
    else:
        try: return int(value_str)
        except ValueError:
            try: return float(value_str)
            except ValueError:
                # Return as string, stripping potential single quotes from names/enums
                return value_str.strip("'")


def parse_properties_recursive(line: str) -> Dict[str, Any]:
    """Parses a line assuming a single Key=Value structure, using recursive value parsing."""
    properties = {}
    # Match Key = Value structure, allowing '.' in Key
    # Make value part greedy to capture everything after '='
    # Handle optional quotes around key for UE5.2+
    match = re.match(r'\s*("?[a-zA-Z0-9_.]+"?)\s*=\s*(.*)\s*', line)
    if match:
        key = match.group(1).strip().strip('"') # Remove quotes from key if present
        raw_value = match.group(2).strip()
        properties[key] = parse_value(raw_value)
    # Handle lines that might just be flags (like bAdvancedView)
    elif line and '=' not in line and not line.startswith(('/', '#', '"', '(', ')', '<', '>')): # Avoid other syntax
       # Assume boolean flags if no '=' is present and looks like a boolean name
       if line.startswith(('b', 'bCan', 'bHas', 'bIs')):
             properties[line.strip()] = True
       # else:
       #     print(f"Warning: Line without '=' treated as non-boolean: {line}")

    return properties


def parse_pin_details(pin_content: str) -> Dict[str, Any]:
    """ Parses the complex content within CustomProperties Pin(...) """
    # Treat the entire content as a dictionary structure within parentheses
    details = parse_value(f"({pin_content})")
    if not isinstance(details, dict):
        # Fallback: Try parsing line by line if initial parse fails
        print(f"Warning: Initial pin content parse failed. Falling back to line-by-line. Content: {pin_content[:100]}...")
        details = {}
        buffer = ""
        paren_level = 0
        for char in pin_content:
            buffer += char
            if char == '(': paren_level += 1
            elif char == ')': paren_level -= 1
            elif char == ',' and paren_level == 0:
                details.update(parse_properties_recursive(buffer.strip(',')))
                buffer = ""
        if buffer.strip(): details.update(parse_properties_recursive(buffer))

    # --- Post-Processing and Flattening (as before) ---
    if "LinkedTo" in details:
        linked_to_val = details["LinkedTo"]
        processed_links = []
        if isinstance(linked_to_val, list):
            for item in linked_to_val:
                 if isinstance(item, str): processed_links.extend(parse_linked_to(item))
                 elif isinstance(item, (list, tuple)) and len(item) == 2: processed_links.append((str(item[0]).strip('"'), str(item[1])))
                 elif isinstance(item, dict):
                     node_name = item.get("Node") or item.get("_value_0") # Check both common patterns
                     pin_id = item.get("Pin") or item.get("_value_1")
                     if node_name and pin_id: processed_links.append((str(node_name).strip('"'), str(pin_id)))
                 else:
                     print(f"Warning: Unhandled item type in LinkedTo list: {type(item)} - {item}")
            details["LinkedTo"] = processed_links
        elif isinstance(linked_to_val, str): details["LinkedTo"] = parse_linked_to(linked_to_val)
        elif isinstance(linked_to_val, dict) and not linked_to_val: details["LinkedTo"] = []
        elif linked_to_val is None: details["LinkedTo"] = [] # Handle explicit None
        else: print(f"Warning: Unhandled type for LinkedTo: {type(linked_to_val)} - {linked_to_val}")


    # Flatten PinType structure
    if 'PinType' in details and isinstance(details['PinType'], dict):
        pin_type_dict = details.pop('PinType')
        for pt_key, pt_value in pin_type_dict.items():
            clean_key = pt_key.replace("_value_", "") if pt_key.startswith("_value_") else pt_key
            details[f'PinType.{clean_key}'] = pt_value

    # Handle UE5 alternative PinType naming (PinType_0_...)
    keys_to_flatten = [k for k in details if k.startswith("PinType_")]
    for key in keys_to_flatten:
        # Ensure the key format is PinType_INDEX_PropertyName
        parts = key.split('_', 2)
        if len(parts) == 3 and parts[1].isdigit():
            base_key_name = parts[2] # Get part after PinType_N_
            details[f'PinType.{base_key_name}'] = details.pop(key)

    # Convert boolean strings to actual booleans recursively
    def convert_bools(data):
        if isinstance(data, dict):
            for key, value in list(data.items()):
                 if isinstance(value, str):
                     if value.lower() == 'true': data[key] = True
                     elif value.lower() == 'false': data[key] = False
                 elif isinstance(value, (dict, list)):
                     convert_bools(value)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                 if isinstance(item, str):
                     if item.lower() == 'true': data[i] = True
                     elif item.lower() == 'false': data[i] = False
                 elif isinstance(item, (dict, list)):
                     convert_bools(item)
    convert_bools(details)

    # Ensure PinId is present (fallback)
    if 'PinId' not in details:
        match_id = re.search(r'PinId=([a-zA-Z0-9-]+(?:_[a-zA-Z0-9-]+)*)', pin_content) # Allow underscores in PinID
        if match_id: details['PinId'] = match_id.group(1)

    return details


def parse_linked_to(linked_to_content: str) -> List[Tuple[str, str]]:
    """ Parses the raw string content found *within* LinkedTo=(...). """
    links = []
    # Use regex to find all pairs of NodeReference + PinID
    # Example: K2Node_VariableSet_11 8CA811E5... or "Node Name with Spaces" PinID_Blah
    matches = LINKED_TO_PAIR_REGEX.findall(linked_to_content)
    for match_tuple in matches:
        if len(match_tuple) == 2:
            node_ref = match_tuple[0].strip('"') # Remove quotes if present
            pin_id = match_tuple[1]
            if node_ref and pin_id:
                links.append((node_ref, pin_id))
            # --- Add Debug Print ---
            # else:
            #     print(f"DEBUG (parse_linked_to): Skipped potential partial match: NodeRef='{node_ref}', PinID='{pin_id}' from content: '{linked_to_content[:50]}...'")
            # --------------------
        # --- Add Debug Print ---
        # elif match_tuple:
        #     print(f"DEBUG (parse_linked_to): Regex found unexpected tuple length {len(match_tuple)}: {match_tuple} from content: '{linked_to_content[:50]}...'")
        # --------------------

    # --- Add Debug Print ---
    # if not links and linked_to_content.strip():
    #     print(f"DEBUG (parse_linked_to): No links extracted via regex from non-empty content: '{linked_to_content}'")
    # elif links:
    #     print(f"DEBUG (parse_linked_to): Extracted links: {links} from content: '{linked_to_content}'")
    # --------------------
    return links


def parse_variable_reference(var_ref_val: Any) -> Optional[str]:
     """ Parses VariableReference value (string or dict) to get MemberName. """
     if isinstance(var_ref_val, dict):
         member_name = var_ref_val.get("MemberName")
         if not member_name and "MemberReference" in var_ref_val and isinstance(var_ref_val["MemberReference"], dict):
              member_name = var_ref_val["MemberReference"].get("MemberName")
         return str(member_name).strip('"') if member_name else None
     elif isinstance(var_ref_val, str):
         match = VAR_REF_REGEX.search(var_ref_val)
         if match: return match.group(1).strip('"')
     return None

def extract_member_name(func_ref_val: Any) -> Optional[str]:
    """Extracts MemberName from FunctionReference or DelegateReference."""
    name = None
    if isinstance(func_ref_val, dict):
        name = func_ref_val.get("MemberName")
        # Check nested MemberReference common in newer UE versions
        if not name and "MemberReference" in func_ref_val and isinstance(func_ref_val["MemberReference"], dict):
             name = func_ref_val["MemberReference"].get("MemberName")
    elif isinstance(func_ref_val, str):
        # Try extracting from content within parens if passed directly
        match = MEMBER_NAME_REGEX.search(func_ref_val)
        if match: name = match.group(1)
    return str(name).strip('"') if name else None

# --- START OF MODIFIED FUNCTION ---
def extract_simple_name_from_path(path: Optional[Union[str, Any]]) -> Optional[str]:
     """Extracts the final component (class/struct/enum name) from a UE path string."""
     # --- (Keep Existing Implementation - Assumed Sufficient for now) ---
     if not path: return None
     path_str = str(path) # Ensure it's a string

     # Handle potential nested structures like {'_value_0': '/Script/...'}
     if isinstance(path, dict):
         path_str = str(path.get('_value_0', path_str)) # Use _value_0 if present, else original dict str
     elif isinstance(path, list) and len(path) > 0:
         path_str = str(path[0]) # Take first element if it's a list

     # Try extracting from typical paths like Class'/Script/...' or /Script/...
     match = CLEAN_NAME_REGEX.search(path_str)
     name = None
     if match:
         name = match.group(1).strip("'\"")
     elif '/' not in path_str and ':' not in path_str and '.' not in path_str:
          # Handle direct names like "MyActor" or "MyEnum"
          name = path_str.strip("'\"")

     if name:
         # Remove _C suffix for class names
         if name.endswith('_C'): name = name[:-2]
         # Handle cases like 'EdGraphPin_0' from older formats if needed
         # if re.match(r'^[a-zA-Z_]+_[0-9]+$', name): name = name.rsplit('_',1)[0] # Might be too aggressive
         # Handle Enum::Value case
         if '::' in name: name = name.split('::')[0]
         return name

     # Fallback: If no clean name found via regex or direct check, return None
     return None
# --- END OF MODIFIED FUNCTION ---

# --- START OF NEW FUNCTION ---
def parse_struct_default_value(value_str: str) -> Optional[str]:
    """
    Parses simple struct default value strings like (TagName="...") or (X=...,Y=...)
    Returns the core information string or None if parsing fails.
    """
    value_str = value_str.strip()
    if not (value_str.startswith('(') and value_str.endswith(')')):
       return None # Not the expected format

    content = value_str[1:-1].strip()
    if not content: return "()" # Empty struct default

    # Handle GameplayTag specifically
    tag_match = re.match(r'TagName="([^"]*)"', content, re.IGNORECASE)
    if tag_match:
       return f'{tag_match.group(1)}' # Return just the tag name

    # Handle simple Vector/Rotator like structures (X=...,Y=...,Z=...)
    # Extract key-value pairs, format them simply
    parts = []
    # Basic split, assumes simple structure without nested parens in default value itself
    raw_parts = re.findall(r'([a-zA-Z]+)=([^,)]+)', content)
    for key, val_raw in raw_parts:
        # Attempt to format float values nicely
        try:
            num_val = float(val_raw)
            if num_val.is_integer():
                formatted_val = str(int(num_val))
            else:
                formatted_val = f"{num_val:.2f}".rstrip('0').rstrip('.') # Keep up to 2 decimal places
        except ValueError:
            formatted_val = val_raw # Keep as string if not a number
        parts.append(f"{key}={formatted_val}")

    if parts:
       return f"({', '.join(parts)})"

    # Fallback if no specific pattern matched inside parens
    return f"({content})"
# --- END OF NEW FUNCTION ---


def extract_specific_type(text_block: str, regex: re.Pattern, capture_group: int = 1, key_name: Optional[str] = None) -> Optional[str]:
    """
    Extracts a type name or full string using a specific regex from a block of text.
    Optionally requires the key_name to be present on the matched line.
    """
    for line in text_block.splitlines():
        line = line.strip()
        if key_name and not line.startswith(key_name) and not line.startswith(f'"{key_name}"'):
            continue # Skip lines that don't start with the expected key

        match = regex.search(line)
        if match:
            try:
                captured_value = match.group(capture_group).strip("'\"") # Strip quotes/apostrophes
                return captured_value
            except IndexError:
                 print(f"Warning: Regex {regex.pattern} found match but capture group {capture_group} is invalid for line: {line}")
                 return None # Invalid group index
    return None # Not found in any line

def extract_macro_path(macro_ref_val: Any) -> Optional[str]:
     """Extracts the macro graph path."""
     path = None
     if isinstance(macro_ref_val, dict):
         # Check common keys used for macro references
         path = macro_ref_val.get("MacroGraph") or \
                macro_ref_val.get("Graph") or \
                macro_ref_val.get("AssetPtr") or \
                macro_ref_val.get("ObjectPath") or \
                macro_ref_val.get("_value_0") # Fallback for simple paren value
     elif isinstance(macro_ref_val, str):
         match = MACRO_PATH_REGEX.search(macro_ref_val)
         if match: path = match.group(1)
         else: path = macro_ref_val # Fallback if just a raw path string
     return str(path).strip("'\"") if path else None

def format_statistics(stats: Dict[str, Any]) -> str:
    """Formats parsing statistics into a Markdown string."""
    lines = []
    total_nodes = stats.get("total_nodes", 0)
    link_resolved = stats.get("links_resolved", 0)
    link_unresolved = stats.get("links_unresolved", 0)
    unresolved_name_lookups = stats.get("unresolved_name_lookups", 0)
    unresolved_pin_lookups = stats.get("unresolved_pin_lookups", 0)
    missing_nodes = stats.get("missing_nodes", 0)
    comment_count = stats.get("comment_count", 0)

    lines.append(f"**Total Nodes Parsed:** {total_nodes}")
    if "links_resolved" in stats or "links_unresolved" in stats:
        unresolved_details = []
        if unresolved_name_lookups > 0: unresolved_details.append(f"Name Lookups: {unresolved_name_lookups}")
        if unresolved_pin_lookups > 0: unresolved_details.append(f"Pin Lookups: {unresolved_pin_lookups}")
        if missing_nodes > 0: unresolved_details.append(f"Missing Nodes: {missing_nodes}")
        unresolved_str = f" ({', '.join(unresolved_details)})" if unresolved_details else ""
        lines.append(f"**Link Resolution:** Resolved: {link_resolved}, Unresolved: {link_unresolved}{unresolved_str}")
    if comment_count > 0:
        lines.append(f"**Comments Found:** {comment_count}")
    # Add more lines for other stats if needed
    return "\n".join(lines)

# --- END OF FILE blueprint_parser/utils.py ---