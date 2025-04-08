# blueprint_parser/formatter/mermaid_formatter.py
from typing import Dict, List, Set, Optional
import re
from ..nodes import (Node, K2Node_IfThenElse, K2Node_ExecutionSequence, K2Node_VariableSet, 
                    K2Node_CallFunction, K2Node_Event, K2Node_CustomEvent, 
                    K2Node_EnhancedInputAction, K2Node_DynamicCast, K2Node_ForEachLoop,
                    K2Node_Switch, K2Node_Timeline)

class MermaidFormatter:
    def __init__(self, nodes: Dict[str, Node]):
        self.nodes = nodes
        self.node_id_map = {}  # Map GUIDs to Mermaid-safe IDs
        self.mermaid_lines = []
        self.processed_nodes = set()
        
    def _sanitize_id(self, text: str) -> str:
        """Make a string safe for use as a Mermaid node ID"""
        # Remove special characters and ensure starts with letter
        sanitized = re.sub(r'[^\w]', '_', text)
        if not sanitized or not sanitized[0].isalpha():
            sanitized = 'n' + sanitized
        return sanitized
        
    def _generate_node_id(self, node: Node) -> str:
        """Generate a Mermaid-compatible ID for a node"""
        guid = node.guid
        if guid in self.node_id_map:
            return self.node_id_map[guid]
            
        # Create a short, sanitized ID from the GUID
        safe_id = self._sanitize_id(f"node_{guid[:8]}")
        # Ensure uniqueness
        if safe_id in self.node_id_map.values():
            safe_id = self._sanitize_id(f"node_{guid[:12]}")
        self.node_id_map[guid] = safe_id
        return safe_id
        
    def _sanitize_label(self, text: str) -> str:
        """Make a string safe for use as a Mermaid node label"""
        # Replace quotes with escaped quotes, and other problematic characters
        return (text.replace('"', '\\"')
                   .replace(':', '-')
                   .replace('|', '/')
                   .replace('&', 'and')
                   .replace('<', 'lt')
                   .replace('>', 'gt'))
        
    def _format_node_label(self, node: Node) -> str:
        """Create a readable label for node display"""
        label = ""
        
        if isinstance(node, K2Node_Event) or isinstance(node, K2Node_CustomEvent):
            event_name = getattr(node, 'event_function_name', None) or getattr(node, 'custom_function_name', None) or "Event"
            label = f"Event- {self._sanitize_label(event_name)}"
        elif isinstance(node, K2Node_EnhancedInputAction):
            action_name = getattr(node, 'input_action_name', None) or "Input"
            label = f"Input- {self._sanitize_label(action_name)}"
        elif isinstance(node, K2Node_VariableSet):
            var_name = getattr(node, 'variable_name', 'Unknown')
            label = f"Set {self._sanitize_label(var_name)}"
        elif isinstance(node, K2Node_CallFunction):
            func_name = getattr(node, 'function_name', 'Unknown')
            label = f"Call {self._sanitize_label(func_name)}"
        elif isinstance(node, K2Node_IfThenElse):
            label = "If Condition"
        elif isinstance(node, K2Node_ExecutionSequence):
            label = "Sequence"
        elif isinstance(node, K2Node_DynamicCast):
            cast_type = getattr(node, 'target_type', 'Unknown')
            label = f"Cast to {self._sanitize_label(cast_type)}"
        elif isinstance(node, K2Node_ForEachLoop):
            label = "For Each Loop"
        elif isinstance(node, K2Node_Switch):
            label = "Switch"
        elif isinstance(node, K2Node_Timeline):
            timeline_name = getattr(node, 'timeline_name', 'Timeline')
            label = f"Timeline- {self._sanitize_label(timeline_name)}"
        else:
            label = self._sanitize_label(node.node_type)
            
        return f"[\"{label}\"]"
    
    def _sanitize_edge_label(self, text: str) -> str:
        """Make a string safe for use as an edge label"""
        sanitized = self._sanitize_label(text)
        # Keep edge labels very short to avoid syntax issues
        if len(sanitized) > 15:
            sanitized = sanitized[:12] + "..."
        return sanitized
    
    def _get_node_style(self, node: Node) -> str:
        """Return style definition for different node types"""
        node_id = self.node_id_map.get(node.guid, "")
        if not node_id:
            return ""
            
        if isinstance(node, (K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction)):
            return f"    style {node_id} fill:#f96,stroke:#333,stroke-width:2px"
        elif isinstance(node, K2Node_IfThenElse):
            return f"    style {node_id} fill:#bbf,stroke:#333"
        elif isinstance(node, K2Node_CallFunction):
            return f"    style {node_id} fill:#bfb,stroke:#333"
        elif isinstance(node, K2Node_VariableSet):
            return f"    style {node_id} fill:#fbf,stroke:#333"
        elif isinstance(node, K2Node_Switch):
            return f"    style {node_id} fill:#fbb,stroke:#333"
        
        return ""
        
    def _trace_execution_path(self, current_node: Node, processed: Set[str]):
        """Recursively trace execution paths for Mermaid diagram"""
        if not current_node or current_node.guid in processed:
            return
            
        current_guid = current_node.guid
        processed.add(current_guid)
        self.processed_nodes.add(current_guid)
        
        # Generate node ID and add to diagram
        node_id = self._generate_node_id(current_node)
        node_label = self._format_node_label(current_node)
        self.mermaid_lines.append(f"    {node_id}{node_label}")
        
        # Add style
        node_style = self._get_node_style(current_node)
        if node_style:
            self.mermaid_lines.append(node_style)
        
        # Process branches based on node type
        if isinstance(current_node, K2Node_IfThenElse):
            # If/Else branching
            true_pin = current_node.get_true_pin()
            false_pin = current_node.get_false_pin()
            
            if true_pin and true_pin.linked_pins:
                true_node = self.nodes.get(true_pin.linked_pins[0].node_guid)
                if true_node:
                    true_id = self._generate_node_id(true_node)
                    self.mermaid_lines.append(f"    {node_id} -->|True| {true_id}")
                    self._trace_execution_path(true_node, processed.copy())
                    
            if false_pin and false_pin.linked_pins:
                false_node = self.nodes.get(false_pin.linked_pins[0].node_guid)
                if false_node:
                    false_id = self._generate_node_id(false_node)
                    self.mermaid_lines.append(f"    {node_id} -->|False| {false_id}")
                    self._trace_execution_path(false_node, processed.copy())
                    
        elif isinstance(current_node, K2Node_ExecutionSequence):
            # Sequence with multiple outputs
            for i, pin in enumerate(current_node.get_execution_output_pins()):
                if pin and pin.linked_pins:
                    next_node = self.nodes.get(pin.linked_pins[0].node_guid)
                    if next_node:
                        next_id = self._generate_node_id(next_node)
                        self.mermaid_lines.append(f"    {node_id} -->|{i+1}| {next_id}")
                        self._trace_execution_path(next_node, processed.copy())
                        
        elif isinstance(current_node, K2Node_Switch):
            # Switch with multiple cases
            case_pins = current_node.get_case_pins()
            default_pin = current_node.get_default_pin()
            
            for pin in case_pins:
                if pin and pin.linked_pins:
                    next_node = self.nodes.get(pin.linked_pins[0].node_guid)
                    if next_node:
                        pin_name = self._sanitize_edge_label(pin.name or "Case")
                        next_id = self._generate_node_id(next_node)
                        self.mermaid_lines.append(f"    {node_id} -->|{pin_name}| {next_id}")
                        self._trace_execution_path(next_node, processed.copy())
                        
            if default_pin and default_pin.linked_pins:
                default_node = self.nodes.get(default_pin.linked_pins[0].node_guid)
                if default_node:
                    default_id = self._generate_node_id(default_node)
                    self.mermaid_lines.append(f"    {node_id} -->|Default| {default_id}")
                    self._trace_execution_path(default_node, processed.copy())
                    
        elif isinstance(current_node, K2Node_ForEachLoop):
            # ForEach with loop body and completed
            loop_pin = current_node.get_loop_body_pin()
            completed_pin = current_node.get_completed_pin()
            
            if loop_pin and loop_pin.linked_pins:
                loop_node = self.nodes.get(loop_pin.linked_pins[0].node_guid)
                if loop_node:
                    loop_id = self._generate_node_id(loop_node)
                    self.mermaid_lines.append(f"    {node_id} -->|Loop| {loop_id}")
                    self._trace_execution_path(loop_node, processed.copy())
                    
            if completed_pin and completed_pin.linked_pins:
                completed_node = self.nodes.get(completed_pin.linked_pins[0].node_guid)
                if completed_node:
                    completed_id = self._generate_node_id(completed_node)
                    self.mermaid_lines.append(f"    {node_id} -->|Done| {completed_id}")
                    self._trace_execution_path(completed_node, processed.copy())
                    
        else:
            # Standard execution flow
            exec_pin = current_node.get_execution_output_pin()
            if exec_pin and exec_pin.linked_pins:
                next_node = self.nodes.get(exec_pin.linked_pins[0].node_guid)
                if next_node:
                    next_id = self._generate_node_id(next_node)
                    self.mermaid_lines.append(f"    {node_id} --> {next_id}")
                    self._trace_execution_path(next_node, processed.copy())
    
    def format_graph(self) -> str:
        """Generate complete Mermaid diagram syntax for Blueprint"""
        try:
            self.mermaid_lines = ["graph TD"]
            self.processed_nodes = set()
            
            # Find entry points (events and inputs)
            entry_points = []
            for node in self.nodes.values():
                if (isinstance(node, (K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction)) or 
                    "Event" in node.node_type or "Input" in node.node_type):
                    entry_points.append(node)
            
            # If no entry points found, add a note
            if not entry_points:
                self.mermaid_lines.append('    note["No entry points found in blueprint"]')
                return "\n".join(self.mermaid_lines)
                
            # Sort by position for consistent ordering
            entry_points.sort(key=lambda n: (n.position[1], n.position[0]))
            
            # Trace execution from each entry point
            for entry in entry_points:
                self._trace_execution_path(entry, set())
            
            # If no nodes were processed after tracing, add a placeholder
            if len(self.mermaid_lines) <= 1:
                self.mermaid_lines.append('    note["No executable nodes found in blueprint"]')
            
            # Construct the complete diagram syntax
            diagram_text = "\n".join(self.mermaid_lines)
            
            # Simple validation to catch obvious errors
            if "undefined" in diagram_text or "<script" in diagram_text:
                return 'graph TD\n    error["Potentially unsafe content detected in diagram"]'
                
            return diagram_text
            
        except Exception as e:
            # Return a valid diagram with error information
            return f'graph TD\n    error["Error generating diagram: {str(e).replace(chr(34), chr(39))}"]'