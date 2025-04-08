# blueprint_parser/formatter/ai_readable_markdown.py

import json
from datetime import datetime
from typing import Dict, Optional, Any

from ..parser import BlueprintParser
from ..nodes import (
    Node, Pin, EdGraphNode_Comment, K2Node_VariableSet, K2Node_VariableGet, 
    K2Node_CallFunction, K2Node_MacroInstance, K2Node_CustomEvent, K2Node_Event,
    K2Node_EnhancedInputAction, K2Node_SwitchEnum, K2Node_DynamicCast, 
    K2Node_MakeStruct, K2Node_BreakStruct
)
from ..utils import extract_simple_name_from_path
from .formatter import BaseFormatter

class AIReadableFormatter(BaseFormatter):
    """Formats blueprint data into a detailed, structured JSON format for AI."""

    def format_graph(self, input_filename: Optional[str] = None) -> str:
        """Formats the graph into a structured JSON format for AI consumption."""
        ai_data = {
            "schema_version": "1.1", # Increment version slightly
            "source_name": input_filename or "Pasted Blueprint",
            "generation_timestamp": datetime.now().isoformat(),
            "stats": self.parser.stats if hasattr(self.parser, 'stats') else {},
            "nodes": [],
            "comments": [],
            "entry_points": [node.guid for node in self._get_execution_start_nodes()]
        }

        # Add functional nodes
        if hasattr(self.parser, 'nodes') and self.parser.nodes:
            for node_guid, node in self.parser.nodes.items():
                if not isinstance(node, EdGraphNode_Comment):
                    ai_data["nodes"].append(self._format_node_for_ai(node))

        # Add comment nodes separately
        if hasattr(self.parser, 'comments') and self.parser.comments:
            for node_guid, node in self.parser.comments.items():
                ai_data["comments"].append(self._format_comment_for_ai(node))


        # Return formatted JSON
        try:
            # Use default=str to handle potential non-serializable types gracefully
            return json.dumps(ai_data, indent=2, default=str)
        except TypeError as e:
             print(f"Error serializing AI data to JSON: {e}", file=sys.stderr)
             # Fallback if default=str still fails (unlikely)
             return json.dumps({"error": f"JSON serialization failed: {e}"}, indent=2)


    def _format_node_for_ai(self, node: Node) -> Dict:
        """Formats a single functional node for the AI structure."""
        node_data = {
            "guid": node.guid,
            "name": node.name, # Original Name property
            "node_type": node.node_type, # Simplified type
            "ue_class": node.ue_class, # Full UE class path
            "position": {"x": node.position[0], "y": node.position[1]},
            "is_pure": node.is_pure(),
            "is_latent": node.is_latent,
            "node_comment": node.node_comment, # Node's direct comment
            "properties": {}, # Store key properties relevant to the node type
            "pins": [self._format_pin_for_ai(pin) for pin in node.pins.values()]
        }

        # Add type-specific properties
        if isinstance(node, K2Node_VariableSet) or isinstance(node, K2Node_VariableGet):
             node_data["properties"]["variable_name"] = node.variable_name
             # Attempt to get type from the specific pin if not directly on node
             var_pin = node.get_value_output_pin() if isinstance(node, K2Node_VariableGet) else node.get_value_input_pin()
             node_data["properties"]["variable_type"] = node.variable_type or (var_pin.get_type_signature() if var_pin else None)
        elif isinstance(node, K2Node_CallFunction):
             node_data["properties"]["function_name"] = node.function_name
             node_data["properties"]["function_ref"] = str(node.raw_properties.get("FunctionReference")) # Keep raw ref
        elif isinstance(node, K2Node_MacroInstance):
            node_data["properties"]["macro_type"] = node.macro_type
            node_data["properties"]["macro_graph_path"] = node.macro_graph_path
        elif isinstance(node, K2Node_CustomEvent):
             node_data["properties"]["custom_function_name"] = node.custom_function_name
        elif isinstance(node, K2Node_Event):
             node_data["properties"]["event_function_name"] = node.event_function_name
             node_data["properties"]["event_reference"] = str(node.raw_properties.get("EventReference"))
        elif isinstance(node, K2Node_EnhancedInputAction):
             node_data["properties"]["input_action_name"] = node.input_action_name
             node_data["properties"]["input_action_path"] = node.input_action_path
        elif isinstance(node, K2Node_SwitchEnum):
             node_data["properties"]["enum_type"] = node.enum_type
             node_data["properties"]["enum_path"] = str(node.raw_properties.get("Enum"))
        elif isinstance(node, K2Node_DynamicCast):
             node_data["properties"]["target_type"] = node.target_type
             node_data["properties"]["target_type_path"] = str(node.raw_properties.get("TargetType"))
        elif isinstance(node, K2Node_MakeStruct) or isinstance(node, K2Node_BreakStruct):
             node_data["properties"]["struct_type"] = node.struct_type
             node_data["properties"]["struct_type_path"] = str(node.raw_properties.get("StructType"))
        # Add more type-specific properties as needed

        # Remove None values from properties for cleaner output
        node_data["properties"] = {k: v for k, v in node_data["properties"].items() if v is not None}

        return node_data

    def _format_comment_for_ai(self, node: EdGraphNode_Comment) -> Dict:
         """Formats a comment node for the AI structure."""
         return {
            "guid": node.guid,
            "node_type": node.node_type,
            "ue_class": node.ue_class,
            "position": {"x": node.position[0], "y": node.position[1]},
            "size": {"width": getattr(node, 'NodeWidth', 0), "height": getattr(node, 'NodeHeight', 0)},
            "comment_text": node.comment_text,
            "color": node.comment_color,
             "pins": [] # Comments don't have functional pins
         }

    def _format_pin_for_ai(self, pin: Pin) -> Dict:
        """Formats a pin for the AI structure, including explicit links."""
        pin_data = {
            "id": pin.id,
            "name": pin.name,
            "friendly_name": pin.friendly_name,
            "direction": pin.direction,
            "category": pin.category,
            "sub_category": pin.sub_category,
            "sub_category_object": pin.sub_category_object, # Full path to type if object/struct/enum
            "type_signature": pin.get_type_signature(),
            "is_reference": pin.is_reference,
            "is_const": pin.is_const,
            "container_type": pin.container_type,
            "is_hidden": pin.is_hidden(),
            "is_advanced": pin.is_advanced_view(),
            "default_value": pin.default_value,
            "default_object": pin.default_object,
            "default_struct": pin.default_struct,
            # Explicit Links (Source Pin -> Target Pin)
            "links": [
                 {
                    "target_node_guid": linked_pin.node_guid,
                    "target_pin_id": linked_pin.id
                 } for linked_pin in pin.linked_pins # Use the resolved links
            ]
            # "raw_linked_to": pin.linked_to_guids # Optionally include the raw parsed links for debugging
        }
        # Clean None values
        pin_data = {k: v for k, v in pin_data.items() if v is not None and v != []}
        # Ensure essential keys are present even if None/empty
        for key in ["id", "name", "direction", "category", "links"]:
             if key not in pin_data: pin_data[key] = None if key != "links" else []

        return pin_data