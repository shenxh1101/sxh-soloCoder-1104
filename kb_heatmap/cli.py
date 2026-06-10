from __future__ import annotations

import argparse
import io
import sys
from pathlib import Path

from .cache import detect_changes, load_cache, save_cache
from .exporter import export_dot
from .graph import KnowledgeGraph, build_graph
from .heatmap import render_heatmap
from .report import export_json_report, generate_report
from .trend import export_trend_csv, render_trend_text


def _apply_filters(graph: KnowledgeGraph, args: argparse.Namespace) -> KnowledgeGraph:
    if args.filter_tags:
        graph = graph.filter_by_tags(args.filter_tags)
    if args.filter_folder:
        graph = graph.filter_by_folder(args.filter_folder)
    return graph


def cmd_analyze(args: argparse.Namespace) -> None:
    vault = args.vault
    if not Path(vault).is_dir():
        print(f"Error: '{vault}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    use_cache = not args.no_cache
    cached_notes = None
    changed_files = None

    if use_cache:
        cached_notes = load_cache(vault)
        if cached_notes is not None:
            changed_files = detect_changes(vault, cached_notes)
            changed_count = len(changed_files)
            total = len(cached_notes) + len(
                set(str(p) for p in Path(vault).rglob("*.md")) - set(cached_notes.keys())
            )
            print(f"  ℹ Incremental mode: {changed_count} of {total} notes changed")
        else:
            print("  ℹ No cache found, performing full scan...")

    graph = build_graph(vault, cached_notes=cached_notes, changed_files=changed_files)

    if use_cache:
        save_cache(vault, graph.notes)
        print(f"  ℹ Cache updated ({len(graph.notes)} notes)")

    graph = _apply_filters(graph, args)

    if args.no_color or not sys.stdout.isatty():
        use_color = False
    else:
        use_color = True

    if not args.report_only:
        heatmap = render_heatmap(graph, cols=args.cols, use_color=use_color)
        print(heatmap)

    if args.trend:
        trend = render_trend_text(
            graph,
            period=args.trend_period,
            window_days=args.trend_window,
        )
        print(trend)

    report = generate_report(graph, top_n=args.top)
    print(report)

    if args.trend_csv:
        export_trend_csv(
            graph,
            args.trend_csv,
            period=args.trend_period,
            window_days=args.trend_window,
            mark_absence=True,
        )
        print(f"  ✅ Trend CSV saved to: {args.trend_csv}")

    if args.json_output:
        export_json_report(
            graph,
            args.json_output,
            filter_tags=args.filter_tags,
            filter_folder=args.filter_folder,
        )
        print(f"  ✅ JSON report saved to: {args.json_output}")


def cmd_export(args: argparse.Namespace) -> None:
    vault = args.vault
    if not Path(vault).is_dir():
        print(f"Error: '{vault}' is not a valid directory.", file=sys.stderr)
        sys.exit(1)

    use_cache = not args.no_cache
    cached_notes = load_cache(vault) if use_cache else None
    changed_files = None
    if cached_notes is not None:
        changed_files = detect_changes(vault, cached_notes)

    graph = build_graph(vault, cached_notes=cached_notes, changed_files=changed_files)

    if use_cache:
        save_cache(vault, graph.notes)

    graph = _apply_filters(graph, args)

    output = args.output or "knowledge_graph.dot"
    group_by = None
    if args.group_by_tag:
        group_by = "tag"
    elif args.group_by_folder:
        group_by = "folder"
    export_dot(graph, output, group_by=group_by)
    print(f"  ✅ Graph exported to: {output}")
    print(f"     Render with: dot -Tpng {output} -o graph.png")


def main(argv: list[str] | None = None) -> None:
    try:
        if sys.platform == "win32" and hasattr(sys.stdout, "buffer"):
            utf8_stdout = io.TextIOWrapper(
                sys.stdout.buffer, encoding="utf-8", errors="replace", line_buffering=True
            )
            sys.stdout = utf8_stdout
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        prog="kb-heatmap",
        description="📊 Knowledge Base Heatmap Analyzer — scan Markdown notes, build knowledge graph, and visualize heat",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    shared = argparse.ArgumentParser(add_help=False)
    shared.add_argument("vault", help="Path to the Markdown notes folder")
    shared.add_argument(
        "--filter-tag",
        dest="filter_tags",
        nargs="+",
        help="Filter notes by tags (accepts #tag, tag, mixed case)",
    )
    shared.add_argument("--filter-folder", dest="filter_folder", help="Filter notes by subfolder")
    shared.add_argument("--no-cache", action="store_true", help="Disable incremental cache, force full rescan")
    shared.add_argument("--no-color", action="store_true", help="Disable colored output")

    analyze_parser = subparsers.add_parser(
        "analyze", parents=[shared], help="Analyze knowledge base and show heatmap + report"
    )
    analyze_parser.add_argument("--top", type=int, default=10, help="Number of top hubs to show (default: 10)")
    analyze_parser.add_argument("--cols", type=int, default=20, help="Heatmap columns (default: 20)")
    analyze_parser.add_argument("--report-only", action="store_true", help="Only show report, skip heatmap")
    analyze_parser.add_argument("--json", dest="json_output", help="Export full report to JSON file path")
    analyze_parser.add_argument("--trend", action="store_true", help="Show per-note heat trend in terminal")
    analyze_parser.add_argument(
        "--trend-period",
        choices=["daily", "weekly"],
        default="daily",
        help="Trend granularity (default: daily)",
    )
    analyze_parser.add_argument(
        "--trend-window",
        type=int,
        default=14,
        help="Days to look back for trend (default: 14)",
    )
    analyze_parser.add_argument(
        "--trend-csv",
        dest="trend_csv",
        help="Export per-note trend matrix as CSV (absent periods left blank)",
    )

    export_parser = subparsers.add_parser(
        "export", parents=[shared], help="Export knowledge graph as Graphviz DOT file"
    )
    export_parser.add_argument("-o", "--output", help="Output .dot file path (default: knowledge_graph.dot)")
    group = export_parser.add_mutually_exclusive_group()
    group.add_argument("--group-by-tag", action="store_true", help="Group nodes by tag clusters in DOT")
    group.add_argument("--group-by-folder", action="store_true", help="Group nodes by folder clusters in DOT")

    args = parser.parse_args(argv)

    if args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "export":
        cmd_export(args)
    else:
        parser.print_help()
        sys.exit(1)
