from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional

from .graph import HeatWeights, KnowledgeGraph


HISTORY_FILENAME = ".kb_heatmap_history.jsonl"


def _snapshot_path(vault_path: str) -> Path:
    return Path(vault_path).resolve() / HISTORY_FILENAME


def load_history(vault_path: str, limit: Optional[int] = None) -> list[dict]:
    path = _snapshot_path(vault_path)
    if not path.exists():
        return []
    snapshots: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                snapshots.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    if limit is not None and limit > 0 and len(snapshots) > limit:
        snapshots = snapshots[-limit:]
    return snapshots


def save_snapshot(
    vault_path: str,
    graph: KnowledgeGraph,
    filter_tags: Optional[list[str]] = None,
    filter_folder: Optional[str] = None,
) -> dict:
    snapshot = {
        "timestamp": time.time(),
        "heat_weights": graph.heat_weights.to_dict(),
        "filters": {
            "tags": [t for t in filter_tags] if filter_tags else [],
            "folder": filter_folder or "",
        },
        "total_notes": len(graph.notes),
        "total_links": len(graph.edges),
        "broken_links_count": len(graph.broken_links),
        "notes": {},
    }
    for key, note in graph.notes.items():
        snapshot["notes"][str(note.path)] = {
            "title": note.title,
            "tags": list(note.tags),
            "mtime": note.mtime,
            "heat_all": graph.heat_scores_all.get(key, 0.0),
            "heat_30d": graph.heat_scores_30d.get(key, 0.0),
            "heat_7d": graph.heat_scores_7d.get(key, 0.0),
            "inbound": graph.inbound_count.get(key, 0),
            "outbound": sum(1 for e in graph.edges if e.source == key),
        }
    snapshot["edges"] = [{"source": e.source, "target": e.target} for e in graph.edges]

    path = _snapshot_path(vault_path)
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(snapshot, ensure_ascii=False) + "\n")
    except OSError:
        pass
    return snapshot


def merge_history_with_current(
    history: list[dict],
    graph: KnowledgeGraph,
) -> dict[str, dict[float, float]]:
    note_series: dict[str, dict[float, float]] = {}
    for snap in history:
        ts = snap.get("timestamp")
        if not ts:
            continue
        for path_str, nd in snap.get("notes", {}).items():
            heat = nd.get("heat_all", 0.0)
            if path_str not in note_series:
                note_series[path_str] = {}
            note_series[path_str][ts] = heat
    now = time.time()
    for key, note in graph.notes.items():
        heat = graph.heat_scores_all.get(key, 0.0)
        if key not in note_series:
            note_series[key] = {}
        note_series[key][now] = heat
    return note_series
