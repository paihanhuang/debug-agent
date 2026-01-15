"""CLI entry point for the causal knowledge graph generator."""

from __future__ import annotations
import argparse
import sys
from pathlib import Path

from .graph.builder import GraphBuilder
from .graph.exporter import GraphExporter


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="inference-engine",
        description="Generate causal knowledge graphs from analysis reports",
    )
    
    parser.add_argument(
        "--problem", "-p",
        type=str,
        help="Path to problem description file",
    )
    
    parser.add_argument(
        "--analysis", "-a",
        type=str,
        required=True,
        help="Path to expert analysis report file",
    )
    
    parser.add_argument(
        "--output", "-o",
        type=str,
        default="output.json",
        help="Output file path (default: output.json)",
    )
    
    parser.add_argument(
        "--format", "-f",
        type=str,
        choices=["json", "graphml", "dot", "png", "svg", "html", "mermaid"],
        default="json",
        help="Output format (default: json)",
    )
    
    parser.add_argument(
        "--visualize", "-v",
        type=str,
        help="Additionally generate a visualization (png/svg/html path)",
    )
    
    parser.add_argument(
        "--llm-provider",
        type=str,
        choices=["openai", "anthropic"],
        default="openai",
        help="LLM provider to use (default: openai)",
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    
    args = parser.parse_args()
    
    # Validate inputs
    analysis_path = Path(args.analysis)
    if not analysis_path.exists():
        print(f"Error: Analysis file not found: {args.analysis}", file=sys.stderr)
        sys.exit(1)
    
    problem_path = None
    if args.problem:
        problem_path = Path(args.problem)
        if not problem_path.exists():
            print(f"Error: Problem file not found: {args.problem}", file=sys.stderr)
            sys.exit(1)
    
    try:
        if args.verbose:
            print(f"Using LLM provider: {args.llm_provider}")
            print(f"Building graph from: {args.analysis}")
        
        # Build the graph
        builder = GraphBuilder(llm_provider=args.llm_provider)
        
        if problem_path:
            graph = builder.build_from_files(problem_path, analysis_path)
        else:
            graph = builder.build_from_single_file(analysis_path)
        
        if args.verbose:
            print(f"Extracted {len(graph.get_entities())} entities")
            print(f"Extracted {len(graph.get_relations())} relations")
        
        # Export the graph
        exporter = GraphExporter(graph)
        output_path = Path(args.output)
        
        if args.format == "json":
            exporter.to_json(output_path)
        elif args.format == "graphml":
            exporter.to_graphml(output_path)
        elif args.format == "dot":
            exporter.to_dot(output_path)
        elif args.format == "png":
            exporter.to_png(output_path)
        elif args.format == "svg":
            exporter.to_svg(output_path)
        elif args.format == "html":
            exporter.to_pyvis_html(output_path)
        elif args.format == "mermaid":
            mermaid_str = exporter.to_mermaid()
            output_path.write_text(mermaid_str, encoding="utf-8")
        
        print(f"Graph exported to: {output_path}")
        
        # Additional visualization if requested
        if args.visualize:
            viz_path = Path(args.visualize)
            suffix = viz_path.suffix.lower()
            
            if suffix == ".png":
                exporter.to_png(viz_path)
            elif suffix == ".svg":
                exporter.to_svg(viz_path)
            elif suffix == ".html":
                exporter.to_pyvis_html(viz_path)
            else:
                print(f"Warning: Unknown visualization format: {suffix}", file=sys.stderr)
            
            print(f"Visualization exported to: {viz_path}")
        
        # Print summary
        root_causes = graph.get_root_causes()
        if root_causes:
            print("\nIdentified Root Causes:")
            for rc in root_causes:
                print(f"  - {rc.label}")
        
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
