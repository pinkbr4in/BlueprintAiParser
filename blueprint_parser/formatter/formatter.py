# blueprint_parser/formatter/formatter.py

import json
from datetime import datetime
from typing import Dict, List, Optional, Set, Any, Tuple
import sys

from ..parser import BlueprintParser
from ..nodes import (Node, Pin,  # Added Pin
                    EdGraphNode_Comment, K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction,
                    K2Node_InputAction, K2Node_InputAxisEvent, K2Node_InputKey, K2Node_InputTouch,
                    K2Node_InputAxisKeyEvent, K2Node_InputDebugKey, K2Node_FunctionEntry)
from .path_tracer import PathTracer
from .node_formatter import NodeFormatter
from .data_tracer import DataTracer
from .comment_handler import CommentHandler
from ..utils import format_statistics

class BaseFormatter:
    """Base class for formatting blueprint data."""
    def __init__(self, parser: BlueprintParser):
        self.parser = parser
        # Lazy initialization for handlers/tracers
        self._comment_handler: Optional[CommentHandler] = None
        self._data_tracer: Optional[DataTracer] = None
        self._node_formatter: Optional[NodeFormatter] = None
        self._path_tracer: Optional[PathTracer] = None
        # Clear data tracer cache at the start of formatting
        if self.parser and hasattr(self.parser, 'nodes') and self.parser.nodes: # Ensure parser is ready
            self.data_tracer.clear_cache()
        else:
            print("Warning (BaseFormatter): Parser not fully initialized, skipping cache clear.", file=sys.stderr)


    @property
    def comment_handler(self) -> CommentHandler:
        if self._comment_handler is None:
            if not hasattr(self.parser, 'comments'): self.parser.comments = {} # Safety init
            if not hasattr(self.parser, 'nodes'): self.parser.nodes = {} # Safety init
            self._comment_handler = CommentHandler(self.parser.comments, self.parser.nodes)
            self._comment_handler.associate_comments()
        return self._comment_handler

    @property
    def data_tracer(self) -> DataTracer:
        if self._data_tracer is None:
            self._data_tracer = DataTracer(self.parser)
        return self._data_tracer

    @property
    def node_formatter(self) -> NodeFormatter:
        if self._node_formatter is None:
            # Pass parser and ensure data_tracer is initialized
            self._node_formatter = NodeFormatter(self.parser, self.data_tracer)
        return self._node_formatter

    @property
    def path_tracer(self) -> PathTracer:
        if self._path_tracer is None:
             # Ensure other handlers are initialized first
             self._path_tracer = PathTracer(self.parser, self.node_formatter, self.comment_handler)
        return self._path_tracer

    def format_graph(self, input_filename: Optional[str] = None) -> str:
        """Formats the entire blueprint graph."""
        raise NotImplementedError

    def format_statistics(self) -> str:
        """Formats parsing statistics."""
        # Ensure stats are populated
        if not hasattr(self.parser, 'stats') or not self.parser.stats:
            return "**Statistics:** (Unavailable)"
        return format_statistics(self.parser.stats)

    def _get_execution_start_nodes(self) -> List[Node]:
        """Identifies nodes that start execution paths."""
        start_nodes = []
        if not self.parser or not hasattr(self.parser, 'nodes') or not self.parser.nodes:
            print("Warning (_get_execution_start_nodes): Parser or nodes dictionary is empty.", file=sys.stderr)
            return []

        for node in self.parser.nodes.values():
             # Check specific types known to start execution
            if isinstance(node, (K2Node_Event, K2Node_CustomEvent, K2Node_EnhancedInputAction,
                                 K2Node_InputAction, K2Node_InputAxisEvent, K2Node_InputKey,
                                 K2Node_InputTouch, K2Node_InputAxisKeyEvent, K2Node_InputDebugKey,
                                 K2Node_FunctionEntry)): # Added FunctionEntry
                 # Further check: Ensure it doesn't have incoming execution links (truly a start point)
                input_exec_pin = node.get_execution_input_pin()
                 # Treat pin as having no source if it doesn't exist OR if it exists but has no source_pin_for
                if not input_exec_pin or not input_exec_pin.source_pin_for:
                    start_nodes.append(node)
        # Sort primarily by Y position, then X
        start_nodes.sort(key=lambda n: (n.position[1], n.position[0]))
        return start_nodes

# Import formatters from separate modules
from .human_readable_markdown import EnhancedMarkdownFormatter
from .ai_readable_markdown import AIReadableFormatter

class JsonFormatter(BaseFormatter):
    """Formats blueprint data into JSON (Kept simpler than AI format)."""
    def format_graph(self, input_filename: Optional[str] = None) -> str:
        # Basic JSON output using node.to_dict()
        nodes_list = []
        comments_list = []
        if hasattr(self.parser, 'nodes') and self.parser.nodes:
             nodes_list = [node.to_dict() for node in self.parser.nodes.values()]
        if hasattr(self.parser, 'comments') and self.parser.comments:
             comments_list = [comment.to_dict() for comment in self.parser.comments.values()]

        data = {
            "filename": input_filename or "Pasted Blueprint",
            "timestamp": datetime.now().isoformat(),
            "stats": self.parser.stats if hasattr(self.parser, 'stats') else {},
            "nodes": nodes_list,
            "comments": comments_list
        }
        try:
            # Use default=str to handle potential non-serializable types gracefully
            return json.dumps(data, indent=2, default=str)
        except TypeError as e:
            print(f"Error serializing basic JSON data: {e}", file=sys.stderr)
            return json.dumps({"error": f"JSON serialization failed: {e}"}, indent=2)

# Factory Function
def get_formatter(format_type: str, parser: BlueprintParser) -> BaseFormatter:
    """Gets the appropriate formatter instance."""
    # Ensure parser is valid before creating formatters that depend on it
    if not isinstance(parser, BlueprintParser):
         raise TypeError("Invalid parser object provided to get_formatter")

    format_type_lower = format_type.lower()

    if format_type_lower == 'enhanced_markdown':
        return EnhancedMarkdownFormatter(parser)
    elif format_type_lower == 'ai_readable':
        return AIReadableFormatter(parser)
    elif format_type_lower == 'json': # Basic JSON
        return JsonFormatter(parser)
    # Add MermaidFormatter when ready
    # elif format_type_lower == 'mermaid':
    #     return MermaidFormatter(parser)
    else:
        # Default to Enhanced Markdown if format is unrecognized
        print(f"Warning: Unsupported format type '{format_type}'. Defaulting to 'enhanced_markdown'.", file=sys.stderr)
        return EnhancedMarkdownFormatter(parser)