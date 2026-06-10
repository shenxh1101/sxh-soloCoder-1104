from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from .graph import KnowledgeGraph


_DOT_LABEL_ESCAPE_RE = re.compile(r'(["\\\n\r\t])')
_DOT_ID_STRIP_RE = re.compile(r'[^a-zA-Z0-9_]')


def _dot_escape_label(s: str) -> str:
    if s is None:
        return ""
    def _sub(m):
        ch = m.group(1)
        return {
            "\\": "\\\\",
            '"': '\\"',
            "\n": "\\n",
            "\r": "\\r",
            "\t": "\\t",
        }.get(ch, ch)
    return _DOT_LABEL_ESCAPE_RE.sub(_sub, str(s))


def _dot_safe_id(s: str, idx: Optional[int] = None, prefix: str = "n") -> str:
    cleaned = _DOT_ID_STRIP_RE.sub("_", s)
    if not cleaned or cleaned[0].isdigit():
        cleaned = "_" + cleaned
    if idx is not None:
        cleaned = f"{prefix}{idx}_{cleaned}"
    return cleaned[:80]


def _dot_cluster_id(s: str, idx: Optional[int] = None) -> str:
    cleaned = _DOT_ID_STRIP_RE.sub("_", s)
    if not cleaned:
        cleaned = "cluster"
    if idx is not None:
        cleaned = f"c{idx}_{cleaned}"
    return f"cluster_{cleaned}"


def _heat_to_graphviz_color(heat: float) -> str:
    r = int(heat * 255)
    g = int((1 - abs(heat - 0.5) * 2) * 180)
    b = int((1 - heat) * 255)
    return f"#{r:02x}{g:02x}{b:02x}"


def _tag_cluster_color(tag: str, idx: int) -> str:
    import hashlib
    h = hashlib.md5(tag.encode("utf-8")).hexdigest()
    r = int(h[0:2], 16)
    g = int(h[2:4], 16)
    b = int(h[4:6], 16)
    return f"#{r:02x}{g:02x}{b:02x}"


def export_dot(
    graph: KnowledgeGraph,
    output_path: str,
    group_by: Optional[str] = None,
) -> None:
    lines: list[str] = []
    lines.append('digraph KnowledgeGraph {')
    lines.append('    rankdir=LR;')
    lines.append('    newrank=true;')
    lines.append('    compound=true;')
    lines.append('    node [shape=box, style="rounded,filled", fontname="Arial", margin="0.15,0.1"];')
    lines.append('    edge [color="#888888", arrowsize=0.6, penwidth=0.8];')
    lines.append('')

    max_heat = max(graph.heat_scores.values()) if graph.heat_scores else 1.0
    if max_heat == 0:
        max_heat = 1.0

    key_to_node_id: dict[str, str] = {}
    node_specs: list[tuple[str, str, dict]] = []
    for idx, (key, note) in enumerate(graph.notes.items()):
        node_id = _dot_safe_id(note.title, idx, "n")
        key_to_node_id[key] = node_id
        heat = graph.heat_scores.get(key, 0.0) / max_heat
        color = _heat_to_graphviz_color(heat)
        inbound = graph.inbound_count.get(key, 0)
        outbound = sum(1 for e in graph.edges if e.source == key)
        fontsize = 10 + int(heat * 8)
        penwidth = 1.0 + heat * 2.0
        tags_label = "\\l".join(f"#{_dot_escape_label(t)}" for t in note.tags[:3]) if note.tags else ""
        label_parts = [_dot_escape_label(note.title)]
        if tags_label:
            label_parts.append(tags_label)
        label = "\\l".join(label_parts) + "\\l"
        tooltip = _dot_escape_label(f"{note.title} | in:{inbound} out:{outbound} heat:{heat:.3f}")
        attrs = {
            "fillcolor": color,
            "fontsize": str(fontsize),
            "penwidth": f"{penwidth:.1f}",
            "label": label,
            "tooltip": tooltip,
        }
        node_specs.append((node_id, key, attrs))

    node_groups: dict[str, list[tuple[str, str, dict]]] = {}
    if group_by == "tag":
        tag_notes: dict[str, list[str]] = {}
        for node_id, key, attrs in node_specs:
            note = graph.notes[key]
            if note.tags:
                for tag in note.tags[:1]:
                    tag_notes.setdefault(tag, []).append((node_id, key, attrs))
            else:
                tag_notes.setdefault("(untagged)", []).append((node_id, key, attrs))
        node_groups = tag_notes
    elif group_by == "folder":
        folder_notes: dict[str, list[str]] = {}
        for node_id, key, attrs in node_specs:
            note = graph.notes[key]
            parent = note.path.parent.name if note.path.parent != note.path.parent.parent else "(root)"
            folder_notes.setdefault(parent, []).append((node_id, key, attrs))
        node_groups = folder_notes

    if node_groups:
        for gidx, (group_name, group_nodes) in enumerate(node_groups.items()):
            cid = _dot_cluster_id(group_name, gidx)
            esc_name = _dot_escape_label(group_name)
            lines.append(f'    subgraph "{cid}" {{')
            if group_by == "tag":
                c = _tag_cluster_color(group_name, gidx)
                lines.append(f'        label="#{esc_name}";')
                lines.append(f'        style="rounded,filled";')
                lines.append(f'        fillcolor="{c}33";')
                lines.append(f'        color="{c}";')
            else:
                lines.append(f'        label="{esc_name}/";')
                lines.append(f'        style="rounded,dashed";')
                lines.append(f'        color="#666666";')
            lines.append(f'        fontname="Arial";')
            lines.append(f'        fontsize=11;')
            for node_id, _key, attrs in group_nodes:
                attr_str = ", ".join(f'{k}="{v}"' for k, v in attrs.items())
                lines.append(f'        {node_id} [{attr_str}];')
            lines.append(f'    }}')
            lines.append('')
    else:
        for node_id, _key, attrs in node_specs:
            attr_str = ", ".join(f'{k}="{v}"' for k, v in attrs.items())
            lines.append(f'    {node_id} [{attr_str}];')
        lines.append('')

    for edge in graph.edges:
        src_id = key_to_node_id.get(edge.source)
        tgt_id = key_to_node_id.get(edge.target)
        if src_id and tgt_id:
            src_note = graph.notes.get(edge.source)
            tgt_note = graph.notes.get(edge.target)
            tooltip = ""
            if src_note and tgt_note:
                tooltip = _dot_escape_label(f"{src_note.title} → {tgt_note.title}")
            if tooltip:
                lines.append(f'    {src_id} -> {tgt_id} [tooltip="{tooltip}"];')
            else:
                lines.append(f'    {src_id} -> {tgt_id};')

    lines.append('}')
    Path(output_path).write_text("\n".join(lines), encoding="utf-8")
