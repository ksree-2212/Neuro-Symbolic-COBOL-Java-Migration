from typing import List, Dict, Set, Any, Optional
from backend.app.services.parsing.cobol_adapter import CobolASTAdapter
from backend.app.schemas.ast_graph import GraphNode, GraphEdge, GraphData

class CobolDependencyExtractor:
    """
    Extracts deterministic structural dependencies from parsed COBOL AST.
    Produces typed graph nodes and edges for structural memory.
    """
    def __init__(self, project_id: str, file_id: str, adapter: CobolASTAdapter):
        self.project_id = project_id
        self.file_id = file_id
        self.adapter = adapter
        self.nodes: Dict[str, GraphNode] = {}
        self.edges: List[GraphEdge] = []
        self._edge_keys: Set[str] = set()

    def _add_node(self, node_id: str, label: str, node_type: str, start_line: Optional[int] = None, end_line: Optional[int] = None, props: Optional[Dict[str, Any]] = None):
        if node_id not in self.nodes:
            self.nodes[node_id] = GraphNode(
                id=node_id,
                label=label,
                type=node_type,
                file_id=self.file_id,
                start_line=start_line,
                end_line=end_line,
                properties=props or {}
            )

    def _add_edge(self, source: str, target: str, rel_type: str, props: Optional[Dict[str, Any]] = None):
        key = f"{source}:{rel_type}:{target}"
        if key not in self._edge_keys:
            self._edge_keys.add(key)
            edge_id = f"edge_{len(self.edges) + 1}_{rel_type.lower()}"
            self.edges.append(GraphEdge(
                id=edge_id,
                source=source,
                target=target,
                type=rel_type,
                properties=props or {}
            ))

    def extract_graph(self) -> GraphData:
        program_id = self.adapter.get_program_id()
        prog_node_id = f"prog_{self.project_id}_{program_id}"
        self._add_node(
            prog_node_id,
            label=program_id,
            node_type="Program",
            start_line=self.adapter.program.span.start_line,
            end_line=self.adapter.program.span.end_line
        )

        # 1. Data Division items
        data_items = self.adapter.get_data_items()
        for item in data_items:
            item_node_id = f"var_{self.project_id}_{item.name}"
            self._add_node(
                item_node_id,
                label=item.name,
                node_type="DataItem",
                start_line=item.span.start_line,
                end_line=item.span.end_line,
                props={
                    "level": item.level,
                    "pic": item.pic,
                    "data_type": item.data_type,
                    "usage": item.usage,
                    "redefines": item.redefines
                }
            )
            # Link program defines variable
            self._add_edge(prog_node_id, item_node_id, "DEFINES")

        # 2. Sections & Paragraphs
        paragraph_names = set()
        for sec in self.adapter.get_sections():
            for p in sec.paragraphs:
                paragraph_names.add(p.name)

        for sec in self.adapter.get_sections():
            sec_node_id = f"sec_{self.project_id}_{sec.name}"
            self._add_node(
                sec_node_id,
                label=sec.name,
                node_type="Section",
                start_line=sec.span.start_line,
                end_line=sec.span.end_line
            )
            self._add_edge(prog_node_id, sec_node_id, "CONTAINS")

            for p in sec.paragraphs:
                p_node_id = f"para_{self.project_id}_{p.name}"
                self._add_node(
                    p_node_id,
                    label=p.name,
                    node_type="Paragraph",
                    start_line=p.span.start_line,
                    end_line=p.span.end_line
                )
                self._add_edge(sec_node_id, p_node_id, "CONTAINS")

                # Analyze paragraph statements for fine-grained dependencies
                for stmt in p.statements:
                    if stmt.verb == 'PERFORM':
                        for target in stmt.targets:
                            target_node_id = f"para_{self.project_id}_{target}"
                            # If target is another paragraph
                            self._add_node(target_node_id, label=target, node_type="Paragraph")
                            self._add_edge(p_node_id, target_node_id, "PERFORMS")

                    elif stmt.verb == 'CALL':
                        for target in stmt.targets:
                            if target in paragraph_names:
                                target_node_id = f"para_{self.project_id}_{target}"
                                self._add_node(target_node_id, label=target, node_type="Paragraph")
                                self._add_edge(p_node_id, target_node_id, "CALLS")
                            else:
                                ext_node_id = f"ext_{self.project_id}_{target}"
                                self._add_node(ext_node_id, label=target, node_type="ExternalProgram")
                                self._add_edge(p_node_id, ext_node_id, "CALLS")
                                self._add_edge(prog_node_id, ext_node_id, "CALLS")

                    elif stmt.verb == 'COPY' and stmt.copybook_name:
                        cb_node_id = f"cpy_{self.project_id}_{stmt.copybook_name}"
                        self._add_node(cb_node_id, label=stmt.copybook_name, node_type="Copybook")
                        self._add_edge(p_node_id, cb_node_id, "COPIES")
                        self._add_edge(p_node_id, cb_node_id, "DEPENDS_ON")
                        self._add_edge(prog_node_id, cb_node_id, "COPIES")

                    # Variables READS & WRITES
                    for r_var in stmt.variables_read:
                        var_node_id = f"var_{self.project_id}_{r_var}"
                        self._add_node(var_node_id, label=r_var, node_type="DataItem")
                        self._add_edge(p_node_id, var_node_id, "READS")
                        self._add_edge(p_node_id, var_node_id, "REFERENCES")

                    for w_var in stmt.variables_written:
                        var_node_id = f"var_{self.project_id}_{w_var}"
                        self._add_node(var_node_id, label=w_var, node_type="DataItem")
                        self._add_edge(p_node_id, var_node_id, "WRITES")
                        self._add_edge(p_node_id, var_node_id, "REFERENCES")

        # Copybooks in DATA DIVISION
        data_div = self.adapter.get_divisions().get("DATA")
        if data_div and "copybooks" in data_div.details:
            for cb in data_div.details["copybooks"]:
                cb_node_id = f"cpy_{self.project_id}_{cb}"
                self._add_node(cb_node_id, label=cb, node_type="Copybook")
                self._add_edge(prog_node_id, cb_node_id, "COPIES")

        return GraphData(
            nodes=list(self.nodes.values()),
            edges=self.edges
        )
