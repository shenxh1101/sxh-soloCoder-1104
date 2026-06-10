from __future__ import annotations

import csv
import json
import time
from pathlib import Path
from typing import Optional

from .graph import KnowledgeGraph

BOLD = "\033[1m"
RED = "\033[91m"
YELLOW = "\033[93m"
CYAN = "\033[96m"
GREEN = "\033[92m"
MAGENTA = "\033[95m"
DIM = "\033[2m"
RESET = "\033[0m"


def _format_hubs_list(
    graph: KnowledgeGraph,
    hubs: list[tuple[str, float]],
    scores_map: dict[str, float],
) -> list[str]:
    lines: list[str] = []
    if not hubs:
        lines.append("    (none)")
        return lines
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
    return lines


def _heat_trend_arrow(
    heat_all: float, heat_30d: float, heat_7d: float
) -> str:
    if heat_7d > heat_30d > heat_all:
        return f"{GREEN}↑↑ rising fast{RESET}"
    elif heat_7d > heat_all:
        return f"{GREEN}↑ rising{RESET}"
    elif heat_7d < heat_30d < heat_all:
        return f"{RED}↓↓ cooling fast{RESET}"
    elif heat_7d < heat_all:
        return f"{RED}↓ cooling{RESET}"
    else:
        return f"{DIM}→ stable{RESET}"


def get_tag_cooccurrences(graph: KnowledgeGraph, min_count: int = 1) -> list[tuple[str, str, int]]:
    pairs: list[tuple[str, str, int]] = []
    for key, count in graph.tag_cooccurrence.items():
        if "|" in key:
            tag_a, tag_b = key.split("|", 1)
            if count >= min_count:
                pairs.append((tag_a, tag_b, count))
    pairs.sort(key=lambda x: x[2], reverse=True)
    return pairs


def export_tag_cooccurrence_csv(graph: KnowledgeGraph, output_path: str, min_count: int = 1) -> list[list[str]]:
    pairs = get_tag_cooccurrences(graph, min_count)
    rows: list[list[str]] = [["tag_a", "tag_b", "count"]]
    for a, b, c in pairs:
        rows.append([a, b, str(c)])
    out = Path(output_path)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return rows


def render_tag_cooccurrence(graph: KnowledgeGraph, top_n: int = 10) -> str:
    pairs = get_tag_cooccurrences(graph, 1)
    if not pairs:
        return ""
    lines: list[str] = []
    lines.append(f"  {MAGENTA}{BOLD}🔗 Tag Co-occurrences{RESET}")
    lines.append(f"  {'─' * 40}")
    max_c = max((c for _, _, c in pairs), default=1)
    for tag_a, tag_b, count in pairs[:top_n]:
        bar = "█" * min(int(count / max_c * 30), 30)
        lines.append(f"    #{tag_a:<15} + #{tag_b:<15}  {count:>3}  {DIM}{bar}{RESET}")
    lines.append("")
    return "\n".join(lines)


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
    lines.append(f"    Broken links:      {RED}{len(graph.broken_links)}{RESET}")
    unique_tags = set()
    for note in graph.notes.values():
        unique_tags.update(note.tags)
    lines.append(f"    Unique tags:       {len(unique_tags)}")
    avg_heat = sum(graph.heat_scores_all.values()) / len(graph.heat_scores_all) if graph.heat_scores_all else 0
    lines.append(f"    Average heat:      {avg_heat:.4f}")
    lines.append(f"    7-day avg heat:    {sum(graph.heat_scores_7d.values()) / len(graph.heat_scores_7d):.4f}" if graph.heat_scores_7d else "    7-day avg heat:    (none in window)")
    lines.append(f"    30-day avg heat:   {sum(graph.heat_scores_30d.values()) / len(graph.heat_scores_30d):.4f}" if graph.heat_scores_30d else "    30-day avg heat:   (none in window)")
    lines.append("")

    for window_name, window_key, desc in [
        ("Last 7 Days", "7d", f"{YELLOW}🔥 Core Hubs — {YELLOW}"),
        ("Last 30 Days", "30d", f"{YELLOW}🔥 Core Hubs — {YELLOW}"),
        ("All Time", "all", f"{YELLOW}🔥 Core Hubs — {YELLOW}"),
    ]:
        hubs = graph.get_core_hubs(top_n, window_key)
        lines.append(f"  {RED}{BOLD}{desc}{window_name}{RESET}")
        lines.append(f"  {'─' * 40}")
        lines.extend(_format_hubs_list(graph, hubs,
            graph.heat_scores_7d if window_key == "7d"
            else graph.heat_scores_30d if window_key == "30d"
            else graph.heat_scores_all
        ))
        lines.append("")

    if graph.heat_scores_all:
        lines.append(f"  {MAGENTA}{BOLD}📈 Heat Trend (All-time vs 7-day top movers){RESET}")
        lines.append(f"  {'─' * 40}")
        top_all = graph.get_core_hubs(top_n, "all")
        movers: list[tuple[str, float, float, float]] = []
        for key, heat_all in top_all:
            h30 = graph.heat_scores_30d.get(key, heat_all)
            h7 = graph.heat_scores_7d.get(key, heat_all)
            movers.append((key, heat_all, h30, h7))
        for idx, (key, ha, h3, h7) in enumerate(movers[:10], 1):
            note = graph.notes.get(key)
            title = note.title if note else Path(key).stem
            arrow = _heat_trend_arrow(ha, h3, h7)
            lines.append(f"    {idx:>3}. {title}  [{ha:.3f} → {h7:.3f}] {arrow}")
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

    if graph.broken_links:
        lines.append(f"  {RED}{BOLD}⚠️  Broken / Unresolved Links ({len(graph.broken_links)}){RESET}")
        lines.append(f"  {'─' * 40}")
        grouped: dict[str, list[tuple[str, str]]] = {}
        for bl in graph.broken_links:
            note_title = Path(bl.source_path).stem
            if note_title not in grouped:
                grouped[note_title] = []
            grouped[note_title].append((bl.raw_link, bl.target))
        shown = 0
        for note_title, items in list(grouped.items())[:15]:
            for raw_link, target in items[:3]:
                lines.append(f"      [{note_title}] → [[{raw_link}]]  ({target})")
                shown += 1
                if shown >= 25:
                    break
            if shown >= 25:
                break
        if len(graph.broken_links) > 25:
            lines.append(f"      ... and {len(graph.broken_links) - 25} more")
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

    cooc_text = render_tag_cooccurrence(graph, top_n)
    if cooc_text:
        lines.append(cooc_text)

    lines.append(f"  {BOLD}{'═' * 52}{RESET}")
    lines.append("")
    return "\n".join(lines)


def export_json_report(
    graph: KnowledgeGraph,
    output_path: Optional[str] = None,
    filter_tags: Optional[list[str]] = None,
    filter_folder: Optional[str] = None,
) -> dict:
    overview = {
        "total_notes": len(graph.notes),
        "total_links": len(graph.edges),
        "broken_links_count": len(graph.broken_links),
    }
    unique_tags: set[str] = set()
    for note in graph.notes.values():
        unique_tags.update(note.tags)
    overview["unique_tags"] = len(unique_tags)

    def hub_list(hubs: list[tuple[str, float]], scores: dict[str, float]) -> list[dict]:
        result = []
        for key, heat in hubs:
            note = graph.notes.get(key)
            if not note:
                continue
            result.append({
                "path": str(note.path),
                "title": note.title,
                "heat": heat,
                "inbound": graph.inbound_count.get(key, 0),
                "outbound": sum(1 for e in graph.edges if e.source == key),
                "tags": list(note.tags),
                "mtime": note.mtime,
            })
        return result

    hubs_7d = hub_list(graph.get_core_hubs(50, "7d"), graph.heat_scores_7d)
    hubs_30d = hub_list(graph.get_core_hubs(50, "30d"), graph.heat_scores_30d)
    hubs_all = hub_list(graph.get_core_hubs(50, "all"), graph.heat_scores_all)

    isolated = []
    for key, heat in graph.get_isolated_notes():
        note = graph.notes.get(key)
        if not note:
            continue
        isolated.append({
            "path": str(note.path),
            "title": note.title,
            "heat": heat,
            "tags": list(note.tags),
            "mtime": note.mtime,
        })

    broken_links = []
    for bl in graph.broken_links:
        note = graph.notes.get(bl.source_path)
        broken_links.append({
            "source_path": bl.source_path,
            "source_title": note.title if note else "",
            "raw_link": bl.raw_link,
            "target": bl.target,
        })

    tag_popularity: dict[str, int] = {}
    for note in graph.notes.values():
        for tag in note.tags:
            tag_popularity[tag] = tag_popularity.get(tag, 0) + 1
    top_tags = sorted(tag_popularity.items(), key=lambda x: x[1], reverse=True)
    tags_data = [{"tag": t, "count": c} for t, c in top_tags]

    notes_data = []
    for key, note in graph.notes.items():
        notes_data.append({
            "path": str(note.path),
            "title": note.title,
            "tags": list(note.tags),
            "links_out_count": sum(1 for e in graph.edges if e.source == key),
            "links_in_count": graph.inbound_count.get(key, 0),
            "mtime": note.mtime,
            "heat_all": graph.heat_scores_all.get(key, 0.0),
            "heat_30d": graph.heat_scores_30d.get(key, 0.0),
            "heat_7d": graph.heat_scores_7d.get(key, 0.0),
        })

    edges_data = [{"source": e.source, "target": e.target} for e in graph.edges]

    from .graph import normalize_tags

    filters_applied = {
        "tags": normalize_tags(filter_tags) if filter_tags else [],
        "folder": filter_folder or "",
    }

    cooc_data = [
        {"tag_a": a, "tag_b": b, "count": c}
        for a, b, c in get_tag_cooccurrences(graph, 1)
    ]

    report = {
        "generated_at": time.time(),
        "filters": filters_applied,
        "heat_weights": graph.heat_weights.to_dict(),
        "overview": overview,
        "core_hubs_7d": hubs_7d,
        "core_hubs_30d": hubs_30d,
        "core_hubs_all": hubs_all,
        "isolated_notes": isolated,
        "broken_links": broken_links,
        "top_tags": tags_data,
        "tag_cooccurrences": cooc_data,
        "notes": notes_data,
        "edges": edges_data,
    }

    if output_path:
        Path(output_path).write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return report
