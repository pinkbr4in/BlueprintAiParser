# --- START OF FILE unsupported_nodes.py ---

# blueprint_parser/unsupported_nodes.py

from typing import Optional, Dict

# Dictionary mapping UE class path prefixes or specific paths to a category name.
# Using prefixes allows catching entire groups of related nodes.
# Order matters: more specific patterns should come before general ones if overlap exists.
UNSUPPORTED_NODE_PATTERNS: Dict[str, str] = {
    # Specific nodes we *don't* handle even if they might appear in BPs
    "/Script/Interchange": "Interchange", # Example

    # Major Graph Types
    "/Script/UnrealEd.MaterialGraphNode": "Material",
    "/Script/Engine.MaterialExpression": "Material", # Catches all Material Expressions

    "/Script/AnimGraph.": "Animation", # Catches all AnimGraph nodes

    "/Script/MetasoundEditor.": "Metasound",

    "/Script/NiagaraEditor.": "Niagara",

    "/Script/PCGEditor.": "PCG",

    "/Script/AIGraph.BehaviorTree": "Behavior Tree", # Catches BT nodes
    "/Script/AIGraph.AIGraphNode": "Behavior Tree", # Catches general AI graph nodes often used with BT

    # Add other specific unsupported prefixes or full paths if needed
}

# Nodes that *might* be in unsupported categories but ARE handled by the Blueprint parser
SUPPORTED_EXCEPTIONS = {
    "/Script/UnrealEd.MaterialGraphNode_Comment",
    "/Script/UnrealEd.MaterialGraphNode_Knot",
    "/Script/NiagaraEditor.NiagaraNodeReroute",
    # Add any other nodes here that are explicitly supported despite matching an unsupported pattern
}

def get_unsupported_graph_type(class_path: Optional[str]) -> Optional[str]:
    """
    Checks if a given UE class path corresponds to a known unsupported graph type.

    Args:
        class_path: The full Unreal Engine class path string (e.g., "/Script/Engine.MaterialExpressionAdd").

    Returns:
        The category name (e.g., "Material", "Animation") if it's an unsupported type,
        otherwise None.
    """
    if not class_path:
        return None

    # Check if it's an explicitly supported exception first
    if class_path in SUPPORTED_EXCEPTIONS:
        return None

    # Check against unsupported patterns
    for pattern, category in UNSUPPORTED_NODE_PATTERNS.items():
        if class_path.startswith(pattern):
            return category

    return None

# --- END OF FILE unsupported_nodes.py ---