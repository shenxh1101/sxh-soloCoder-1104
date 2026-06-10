from __future__ import annotations

import os
import sys
from pathlib import Path

from .graph import KnowledgeGraph


HEAT_PALETTE_256 = [
    16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31,
    32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47,
    48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63,
    64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79,
    80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95,
    96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111,
    112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127,
    128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143,
    144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159,
    160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175,
    176, 177, 178, 179, 180, 181, 182, 183, 184, 185, 186, 187, 188, 189, 190, 191,
    196, 197, 198, 199, 200, 201, 202, 203, 204, 205, 206, 207, 208, 209, 210, 211,
]

SIMPLE_PALETTE = [
    (0, 0, 0),
    (20, 0, 40),
    (40, 0, 80),
    (60, 0, 120),
    (0, 40, 130),
    (0, 80, 140),
    (0, 120, 120),
    (0, 160, 80),
    (40, 180, 40),
    (120, 200, 0),
    (200, 200, 0),
    (240, 160, 0),
    (255, 100, 0),
    (255, 40, 0),
    (255, 0, 0),
    (255, 255, 255),
]


def _supports_256_color() -> bool:
    term = os.environ.get("TERM", "")
    if "256color" in term:
        return True
    colorterm = os.environ.get("COLORTERM", "")
    if colorterm in ("truecolor", "24bit"):
        return True
    return False


def _heat_to_color_256(heat: float) -> str:
    idx = int(heat * (len(HEAT_PALETTE_256) - 1))
    idx = max(0, min(idx, len(HEAT_PALETTE_256) - 1))
    return f"\033[48;5;{HEAT_PALETTE_256[idx]}m  \033[0m"


def _heat_to_color_rgb(heat: float) -> str:
    idx = int(heat * (len(SIMPLE_PALETTE) - 1))
    idx = max(0, min(idx, len(SIMPLE_PALETTE) - 1))
    r, g, b = SIMPLE_PALETTE[idx]
    return f"\033[48;2;{r};{g};{b}m  \033[0m"


def _heat_to_color_mono(heat: float) -> str:
    chars = " ░▒▓█"
    idx = int(heat * (len(chars) - 1))
    idx = max(0, min(idx, len(chars) - 1))
    return chars[idx] * 2


def render_heatmap(
    graph: KnowledgeGraph,
    cols: int = 20,
    use_color: bool = True,
) -> str:
    if not graph.heat_scores:
        return "(no notes found)"

    items = sorted(graph.heat_scores.items(), key=lambda x: x[1], reverse=True)
    if use_color and sys.stdout.isatty():
        if _supports_256_color():
            color_fn = _heat_to_color_256
        else:
            color_fn = _heat_to_color_rgb
    else:
        color_fn = _heat_to_color_mono

    lines: list[str] = []
    lines.append("")
    lines.append("  ╔════════════════════════════════════════════════╗")
    lines.append("  ║         📊 Knowledge Base Heatmap              ║")
    lines.append("  ╚════════════════════════════════════════════════╝")
    lines.append("")

    rows = (len(items) + cols - 1) // cols
    for row_idx in range(rows):
        row_cells: list[str] = []
        for col_idx in range(cols):
            item_idx = row_idx * cols + col_idx
            if item_idx < len(items):
                heat = items[item_idx][1]
                row_cells.append(color_fn(heat))
            else:
                row_cells.append("  ")
        lines.append("  " + "".join(row_cells))

    lines.append("")
    lines.append("  Legend: " + " ".join(color_fn(i / 9.0) for i in range(10)) + " Low → High")
    lines.append("")

    label_lines: list[str] = []
    label_lines.append("  Note positions (row-major, heat descending):")
    label_lines.append("  " + "─" * 50)
    for i, (key, heat) in enumerate(items):
        note = graph.notes.get(key)
        title = note.title if note else Path(key).stem
        inbound = graph.inbound_count.get(key, 0)
        outbound = sum(1 for e in graph.edges if e.source == key)
        label_lines.append(f"  {i+1:>4}. [{heat:.3f}] {title}  (←{inbound} →{outbound})")

    lines.extend(label_lines)
    return "\n".join(lines)
