"""Graph export to various formats."""

from __future__ import annotations
import json
from pathlib import Path
from typing import Any

from .models import CausalGraph


class GraphExporter:
    """Export causal graphs to various formats."""
    
    def __init__(self, graph: CausalGraph):
        """Initialize exporter.
        
        Args:
            graph: The causal graph to export.
        """
        self._graph = graph
    
    def to_json(self, path: str | Path | None = None, indent: int = 2) -> str:
        """Export graph to JSON format.
        
        Args:
            path: Optional file path to write to.
            indent: JSON indentation level.
            
        Returns:
            JSON string representation.
        """
        json_str = self._graph.to_json(indent=indent)
        
        if path:
            Path(path).write_text(json_str, encoding="utf-8")
        
        return json_str
    
    def to_graphml(self, path: str | Path) -> None:
        """Export graph to GraphML format.
        
        Args:
            path: File path to write to.
        """
        import networkx as nx
        nx.write_graphml(self._graph.networkx_graph, str(path))
    
    def to_dot(self, path: str | Path | None = None) -> str:
        """Export graph to DOT format for Graphviz.
        
        Args:
            path: Optional file path to write to.
            
        Returns:
            DOT format string.
        """
        lines = ["digraph CausalGraph {"]
        lines.append("    rankdir=BT;")  # Bottom to top for causal flow
        lines.append("    node [shape=box, style=rounded];")
        lines.append("")
        
        # Define node styles by type
        type_colors = {
            "RootCause": "red",
            "Symptom": "orange",
            "Component": "lightblue",
            "Metric": "lightgreen",
            "Hypothesis": "yellow",
            "Action": "lightgray",
            "Observation": "white",
            "Conclusion": "lightpink",
        }
        
        # Add nodes
        for entity in self._graph.get_entities():
            color = type_colors.get(entity.entity_type.value, "white")
            label = entity.label.replace('"', '\\"')
            type_label = entity.entity_type.value
            lines.append(f'    "{entity.id}" [label="{label}\\n({type_label})", fillcolor="{color}", style="filled,rounded"];')
        
        lines.append("")
        
        # Add edges
        for relation in self._graph.get_relations():
            label = relation.relation_type.value
            lines.append(f'    "{relation.source_id}" -> "{relation.target_id}" [label="{label}"];')
        
        lines.append("}")
        
        dot_str = "\n".join(lines)
        
        if path:
            Path(path).write_text(dot_str, encoding="utf-8")
        
        return dot_str
    
    def to_png(self, path: str | Path) -> None:
        """Export graph to PNG image using Graphviz.
        
        Args:
            path: File path to write to.
        """
        try:
            import graphviz
        except ImportError:
            raise ImportError("graphviz package required. Install with: pip install graphviz")
        
        dot_str = self.to_dot()
        
        # Create a graphviz Source and render
        src = graphviz.Source(dot_str)
        
        # Remove extension for graphviz (it adds it)
        path_obj = Path(path)
        output_path = str(path_obj.parent / path_obj.stem)
        
        src.render(output_path, format="png", cleanup=True)
    
    def to_svg(self, path: str | Path) -> None:
        """Export graph to SVG image using Graphviz.
        
        Args:
            path: File path to write to.
        """
        try:
            import graphviz
        except ImportError:
            raise ImportError("graphviz package required. Install with: pip install graphviz")
        
        dot_str = self.to_dot()
        src = graphviz.Source(dot_str)
        
        path_obj = Path(path)
        output_path = str(path_obj.parent / path_obj.stem)
        
        src.render(output_path, format="svg", cleanup=True)
    
    def to_pyvis_html(self, path: str | Path) -> None:
        """Export to interactive HTML visualization using PyVis.
        
        Args:
            path: File path to write to.
        """
        try:
            from pyvis.network import Network
        except ImportError:
            raise ImportError("pyvis package required. Install with: pip install pyvis")
        
        net = Network(
            height="800px",
            width="100%",
            directed=True,
            bgcolor="#ffffff",
            font_color="black",
        )
        
        # Color mapping
        type_colors = {
            "RootCause": "#ff6b6b",
            "Symptom": "#ffa94d",
            "Component": "#74c0fc",
            "Metric": "#69db7c",
            "Hypothesis": "#ffd43b",
            "Action": "#adb5bd",
            "Observation": "#f8f9fa",
            "Conclusion": "#f783ac",
        }
        
        # Add nodes
        for entity in self._graph.get_entities():
            color = type_colors.get(entity.entity_type.value, "#f8f9fa")
            net.add_node(
                entity.id,
                label=f"{entity.label}\n({entity.entity_type.value})",
                color=color,
                title=entity.description or entity.label,
            )
        
        # Add edges
        for relation in self._graph.get_relations():
            net.add_edge(
                relation.source_id,
                relation.target_id,
                title=relation.relation_type.value,
                label=relation.relation_type.value,
            )
        
        net.save_graph(str(path))
    
    def to_mermaid(self) -> str:
        """Export graph to Mermaid diagram format.
        
        Returns:
            Mermaid flowchart string.
        """
        lines = ["flowchart BT"]
        
        # Add nodes with styling
        for entity in self._graph.get_entities():
            label = entity.label.replace('"', "'")
            entity_type = entity.entity_type.value
            
            # Use different node shapes by type
            if entity_type == "RootCause":
                lines.append(f'    {entity.id}[["🔴 {label}<br/>(Root Cause)"]]')
            elif entity_type == "Symptom":
                lines.append(f'    {entity.id}["{label}<br/>(Symptom)"]')
            else:
                lines.append(f'    {entity.id}["{label}<br/>({entity_type})"]')
        
        lines.append("")
        
        # Add edges
        for relation in self._graph.get_relations():
            label = relation.relation_type.value
            lines.append(f'    {relation.source_id} -->|{label}| {relation.target_id}')
        
        return "\n".join(lines)
