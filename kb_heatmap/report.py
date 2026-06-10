from __future__ import annotations

from pathlib import Path

from .graph import KnowledgeGraph

BOLD = "\033[1m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
GREEN = "\033[92m"
DIM = "\033[2m"
RESET = "\033[0m"


def generate_report(graph: KnowledgeGraph, top_n: int = 10) -> str:
    lines: list[str] = []
    lines.append("")
    lines.append(f"  {BOLD}{'═' * 52}{RESET}")
    lines.append(f"  {BOLD}  📋 Knowledge Base Analysis Report{RESET}")
    lines.append(f"  {BOLD}{'═' * 52}{RESET}")
    lines.append("")

    lines.append(f"  {CYAN}Overview{RESET}")
    lines.append(f"  {'─' * 40}")
    lines.append(f"    Total notes:       {len(graph.notes)}")
    lines.append(f"    Total links:       {len(graph.edges)}")
    unique_tags = set()
    for note in graph.notes.values():
        unique_tags.update(note.tags)
    lines.append(f"    Unique tags:       {len(unique_tags)}")
    avg_heat = sum(graph.heat_scores.values()) / len(graph.heat_scores) if graph.heat_scores else 0
    lines.append(f"    Average heat:      {avg_heat:.4f}")
    lines.append("")

    hubs = graph.get_core_hubs(top_n)
    lines.append(f"  {RED}{BOLD}🔥 Core Hubs (Top {len(hubs)}){RESET}")
    lines.append(f"  {'─' * 40}")
    if not hubs:
        lines.append("    (none)")
    for rank, (key, heat) in enumerate(hubs, 1):
        note = graph.notes.get(key)
        title = note.title if note else Path(key).stem
        inbound = graph.inbound_count.get(key, 0)
        outbound = sum(1 for e in graph.edges if e.source == key)
        tags_str = ", ".join(note.tags[:5]) if note else ""
        if tags_str:
            tags_str = f"  #{tags_str}"
        lines.append(
            f"    {rank:>3}. {YELLOW}{heat:.4f}{RESET}  {title}  "
            f"({DIM}←{inbound} →{outbound}{RESET}){tags_str}"
        )
    lines.append("")

    isolated = graph.get_isolated_notes()
    lines.append(f"  {CYAN}{BOLD}🏝️  Isolated Notes ({len(isolated)}){RESET}")
    lines.append(f"  {'─' * 40}")
    if not isolated:
        lines.append("    (none — all notes are connected!)")
    for key, heat in isolated[:20]:
        note = graph.notes.get(key)
        title = note.title if note else Path(key).stem
        tags_str = ", ".join(note.tags[:3]) if note else ""
        tag_display = f"  [{tags_str}]" if tags_str else "  (no tags)"
        lines.append(f"      • {title}{tag_display}")
    if len(isolated) > 20:
        lines.append(f"      ... and {len(isolated) - 20} more")
    lines.append("")

    tag_popularity: dict[str, int] = {}
    for note in graph.notes.values():
        for tag in note.tags:
            tag_popularity[tag] = tag_popularity.get(tag, 0) + 1
    top_tags = sorted(tag_popularity.items(), key=lambda x: x[1], reverse=True)[:15]
    if top_tags:
        lines.append(f"  {GREEN}{BOLD}🏷️  Top Tags{RESET}")
        lines.append(f"  {'─' * 40}")
        for tag, count in top_tags:
            bar = "█" * min(count, 30)
            lines.append(f"    #{tag:<20} {count:>3}  {DIM}{bar}{RESET}")
        lines.append("")

    lines.append(f"  {BOLD}{'═' * 52}{RESET}")
    lines.append("")
    return "\n".join(lines)
