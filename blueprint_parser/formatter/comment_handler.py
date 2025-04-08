# blueprint_parser/formatter/comment_handler.py

from typing import Dict, Optional, List, Set, Tuple
import sys
# --- Use relative imports ---
from ..nodes import Node, EdGraphNode_Comment

# Debug flag
ENABLE_COMMENT_HANDLER_DEBUG = False

class CommentHandler:
    """
    Handles Blueprint comments and associates them with nodes.
    Responsible for mapping comments to nodes based on spatial relationships.
    """
    def __init__(self, comments: Dict[str, EdGraphNode_Comment], nodes: Dict[str, Node]):
        self.comments = comments  # Dictionary of comment nodes
        self.nodes = nodes  # Dictionary of all nodes
        self.comment_map = {}  # Node GUID -> comment text
        self.node_to_comment_map = {}  # Node GUID -> comment GUID
        self.comment_to_nodes_map = {}  # Comment GUID -> [node GUIDs]
        
        # Build the comment associations
        self.associate_comments()

    def associate_comments(self):
        """Associates comments with nodes based on spatial relationships."""
        if ENABLE_COMMENT_HANDLER_DEBUG: print("DEBUG (CommentHandler): Associating comments with nodes...", file=sys.stderr)
        
        # Clear existing maps
        self.comment_map = {}
        self.node_to_comment_map = {}
        self.comment_to_nodes_map = {}
        
        # Build the comment associations
        self._build_comment_map()
        
        # Log results
        contained_nodes = sum(len(nodes) for nodes in self.comment_to_nodes_map.values())
        comment_count = len(self.comments)
        node_count = len(self.nodes)
        
        if ENABLE_COMMENT_HANDLER_DEBUG: 
            print(f"DEBUG (CommentHandler): Associated {contained_nodes} nodes with {comment_count} comments "
                 f"(out of {node_count} total nodes)", file=sys.stderr)

    def _build_comment_map(self):
        """Creates maps between nodes and comments based on spatial relationships."""
        if not self.comments or not self.nodes:
            return
            
        # Get comment nodes from the comments dictionary
        comment_nodes = list(self.comments.values())
        
        # Get non-comment nodes from the nodes dictionary
        non_comment_nodes = [n for n in self.nodes.values() if not isinstance(n, EdGraphNode_Comment)]

        # Sort comments by size (smallest first) for tighter associations
        comment_nodes.sort(key=lambda c: getattr(c, 'NodeWidth', 500) * getattr(c, 'NodeHeight', 300))
        
        # Sort also by position to ensure deterministic associations
        non_comment_nodes.sort(key=lambda n: (n.position[0], n.position[1]))

        # Process each target node
        for target_node in non_comment_nodes:
            node_x, node_y = target_node.position
            node_guid = target_node.guid
            
            # Find all comment nodes that contain this node
            containing_comments = []
            
            for c_node in comment_nodes:
                comment_x, comment_y = c_node.position
                comment_w = getattr(c_node, 'NodeWidth', 500)
                comment_h = getattr(c_node, 'NodeHeight', 300)
                comment_x2 = comment_x + comment_w
                comment_y2 = comment_y + comment_h
                
                # Check if the target node's position is within the comment bounds
                if (comment_x <= node_x < comment_x2 and
                    comment_y <= node_y < comment_y2):
                    containing_comments.append(c_node)
            
            # Sort containing comments from smallest to largest area for more specific associations
            containing_comments.sort(key=lambda c: getattr(c, 'NodeWidth', 500) * getattr(c, 'NodeHeight', 300))
            
            # Associate with the smallest (most specific) containing comment
            if containing_comments:
                smallest_comment = containing_comments[0]
                smallest_comment_guid = smallest_comment.guid
                comment_text = smallest_comment.comment_text
                
                # Store in maps
                self.comment_map[node_guid] = comment_text
                self.node_to_comment_map[node_guid] = smallest_comment_guid
                
                # Update the comment-to-nodes map
                if smallest_comment_guid not in self.comment_to_nodes_map:
                    self.comment_to_nodes_map[smallest_comment_guid] = []
                self.comment_to_nodes_map[smallest_comment_guid].append(node_guid)
            
            # Also check for node's own comment property and add it if no containing comment was found
            if node_guid not in self.comment_map and target_node.node_comment:
                self.comment_map[node_guid] = target_node.node_comment

    def get_comment(self, node_guid: str) -> Optional[str]:
        """Gets the cached comment for a node GUID."""
        return self.comment_map.get(node_guid)

    def get_all_comments_sorted(self) -> List[EdGraphNode_Comment]:
        """Gets all comment nodes, sorted by position."""
        return sorted(
            self.comments.values(),
            key=lambda n: (n.position[1], n.position[0])  # Sort by Y then X
        )
        
    def get_nodes_in_comment(self, comment_guid: str) -> List[str]:
        """Gets all node GUIDs contained within a comment."""
        return self.comment_to_nodes_map.get(comment_guid, [])
    
    def get_comment_for_node(self, node_guid: str) -> Optional[str]:
        """Gets the comment GUID that contains a node."""
        return self.node_to_comment_map.get(node_guid)
    
    def get_comment_groups(self) -> List[Dict]:
        """Returns a list of comment groups with their contained nodes."""
        groups = []
        
        for comment_guid, node_guids in self.comment_to_nodes_map.items():
            if not node_guids:
                continue
                
            comment_node = self.comments.get(comment_guid)
            if not comment_node:
                continue
                
            group = {
                'comment_guid': comment_guid,
                'comment_text': comment_node.comment_text,
                'position': comment_node.position,
                'size': {
                    'width': getattr(comment_node, 'NodeWidth', 500),
                    'height': getattr(comment_node, 'NodeHeight', 300)
                },
                'color': comment_node.comment_color,
                'node_guids': node_guids,
                'node_count': len(node_guids)
            }
            
            groups.append(group)
        
        # Sort groups by Y position
        groups.sort(key=lambda g: g['position'][1])
        
        return groups