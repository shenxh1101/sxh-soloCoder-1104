from __future__ import annotations

from pathlib import Path

from .graph import KnowledgeGraph


def _heat_to_graphviz_color(heat: float) -> str:
    r = int(heat * 255)
    g = int((1 - abs(heat - 0.5) * 2) * 180)
    b = int((1 - heat) * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def export_dot(graph: KnowledgeGraph, output_path: str) -> None:
    lines: list[str] = []
    lines.append('digraph KnowledgeGraph {')
    lines.append('    rankdir=LR;')
    lines.append('    node [shape=box, style="rounded,filled", fontname="Arial"];')
    lines.append('    edge [color="#888888", arrowsize=0.6];')
    lines.append('')

    max_heat = max(graph.heat_scores.values()) if graph.heat_scores else 1.0
    if max_heat == 0:
        max_heat = 1.0

    for key, note in graph.notes.items():
        heat = graph.heat_scores.get(key, 0.0) / max_heat
        color = _heat_to_graphviz_color(heat)
        inbound = graph.inbound_count.get(key, 0)
        outbound = sum(1 for e in graph.edges if e.source == key)
        fontsize = 10 + int(heat * 8)
        penwidth = 1.0 + heat * 2.0
        tags_label = "\\n".join(f"#{t}" for t in note.tags[:3]) if note.tags else ""
        label = note.title
        if tags_label:
            label += "\\n" + tags_label
        lines.append(
            f'    "{note.title}" ['
            f'fillcolor="{color}", '
            f'fontsize={fontsize}, '
            f'penwidth={penwidth:.1f}, '
            f'label="{label}", '
            f'tooltip="←{inbound} →{outbound} heat={heat:.3f}"'
            f'];'
        )

    lines.append('')

    for edge in graph.edges:
        src = graph.notes.get(edge.source)
        tgt = graph.notes.get(edge.target)
        if src and tgt:
            lines.append(f'    "{src.title}" -> "{tgt.title}";')

    lines.append('}')
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
