from typing import List, Dict, Any
from backend.app.schemas.ast_graph import GraphEdge, GraphNode, ChunkInfo

class StructuralConstraintGenerator:
    """
    Generates natural-language structural constraints from graph traversal edges.
    Instructs the LLM translation engine to strictly adhere to preserved dependencies.
    """
    @staticmethod
    def generate_constraints(edges: List[GraphEdge], nodes: List[GraphNode], copybooks: List[str]) -> List[str]:
        constraints = []
        node_labels = {n.id: n.label for n in nodes}

        # Format specific relationship constraints
        for e in edges:
            src = node_labels.get(e.source, e.source)
            tgt = node_labels.get(e.target, e.target)

            if e.type == 'PERFORMS':
                constraints.append(f"{src} performs {tgt}.")
            elif e.type == 'CALLS':
                constraints.append(f"{src} calls {tgt}.")
            elif e.type in ('REFERENCES', 'READS'):
                constraints.append(f"{src} reads data item {tgt}.")
            elif e.type == 'WRITES':
                constraints.append(f"{src} writes data item {tgt}.")
            elif e.type == 'COPIES':
                constraints.append(f"{src} copies definition from {tgt}.")
            elif e.type == 'DEPENDS_ON':
                constraints.append(f"{src} depends on {tgt}.")

        for cb in copybooks:
            constraints.append(f"Ensure record structure from copybook '{cb}' is maintained.")

        if constraints:
            constraints.append(
                "Do not remove, inline, or silently replace these dependencies unless an equivalent "
                "Java method or class implementation is explicitly created."
            )

        return constraints
