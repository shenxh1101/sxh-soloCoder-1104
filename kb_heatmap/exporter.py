from __future__ import annotations

import re
from pathlib import Path

from .graph import KnowledgeGraph


_DOT_UNSAFE_CHARS = re.compile(r'["\\]')
_DOT_ID_UNSAFE = re.compile(r'[^a-zA-Z0-9_\-]')


def _dot_escape(s: str) -> str:
    if s is None:
        return ""
    s = str(s)
    s = s.replace("\\", "\\\\")
    s = s.replace('"', '\\"')
    s = s.replace("\n", "\\n")
    s = s.replace("\r", "\\r")
    s = s.replace("\t", "\\t")
    return s


def _dot_id(s: str) -> str:
    cleaned = _DOT_ID_UNSAFE.sub("_", s)
    if not cleaned:
        cleaned = "node"
    if cleaned[0].isdigit():
        cleaned = "_" + cleaned
    return cleaned


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

    key_to_node_id: dict[str, str] = {}
    for idx, (key, note) in enumerate(graph.notes.items()):
        node_id = f"n{idx}_{_dot_id(note.title)}"
        key_to_node_id[key] = node_id
        heat = graph.heat_scores.get(key, 0.0) / max_heat
        color = _heat_to_graphviz_color(heat)
        inbound = graph.inbound_count.get(key, 0)
        outbound = sum(1 for e in graph.edges if e.source == key)
        fontsize = 10 + int(heat * 8)
        penwidth = 1.0 + heat * 2.0
        tags_label = "\\n".join(f"#{_dot_escape(t)}" for t in note.tags[:3]) if note.tags else ""
        label_parts = [_dot_escape(note.title)]
        if tags_label:
            label_parts.append(tags_label)
        label = "\\n".join(label_parts)
        tooltip = _dot_escape(f"←{inbound} →{outbound} heat={heat:.3f}")
        lines.append(
            f'    {node_id} ['
            f'fillcolor="{color}", '
            f'fontsize={fontsize}, '
            f'penwidth={penwidth:.1f}, '
            f'label="{label}", '
            f'tooltip="{tooltip}"'
            f'];'
        )

    lines.append('')

    for edge in graph.edges:
        src_id = key_to_node_id.get(edge.source)
        tgt_id = key_to_node_id.get(edge.target)
        if src_id and tgt_id:
            lines.append(f'    {src_id} -> {tgt_id};')

    lines.append('}')
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
