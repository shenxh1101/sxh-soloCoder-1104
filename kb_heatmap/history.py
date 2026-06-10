from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from .graph import HeatWeights, KnowledgeGraph, normalize_tags


HISTORY_FILENAME = ".kb_heatmap_history.jsonl"
_WEIGHT_EPSILON = 1e-6


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
                snap = json.loads(line)
                if "timestamp" not in snap:
                    continue
                snapshots.append(snap)
            except json.JSONDecodeError:
                continue
    except OSError:
        return []
    if limit is not None and limit > 0 and len(snapshots) > limit:
        snapshots = snapshots[-limit:]
    return snapshots


def _weights_match(w1: dict, w2: dict, epsilon: float = _WEIGHT_EPSILON) -> bool:
    keys = {"w_inbound", "w_tags", "w_recency", "recency_half_life_days"}
    for k in keys:
        v1 = w1.get(k)
        v2 = w2.get(k)
        if v1 is None or v2 is None:
            return False
        if abs(float(v1) - float(v2)) > epsilon:
            return False
    return True


def _filters_match(f1: dict, f2: dict) -> bool:
    tags1 = sorted([t.lower() for t in f1.get("tags", []) if t])
    tags2 = sorted([t.lower() for t in f2.get("tags", []) if t])
    if tags1 != tags2:
        return False
    folder1 = (f1.get("folder") or "").strip()
    folder2 = (f2.get("folder") or "").strip()
    return folder1 == folder2


def snapshot_matches_config(
    snapshot: dict,
    heat_weights: Optional[HeatWeights] = None,
    filter_tags: Optional[list[str]] = None,
    filter_folder: Optional[str] = None,
) -> bool:
    current_filters = {
        "tags": normalize_tags(filter_tags) if filter_tags else [],
        "folder": filter_folder or "",
    }
    if not _filters_match(current_filters, snapshot.get("filters", {})):
        return False
    if heat_weights is not None:
        if not _weights_match(heat_weights.to_dict(), snapshot.get("heat_weights", {})):
            return False
    return True


def filter_snapshots_by_config(
    snapshots: list[dict],
    heat_weights: Optional[HeatWeights] = None,
    filter_tags: Optional[list[str]] = None,
    filter_folder: Optional[str] = None,
) -> tuple[list[dict], list[dict]]:
    matched: list[dict] = []
    skipped: list[dict] = []
    for snap in snapshots:
        if snapshot_matches_config(snap, heat_weights, filter_tags, filter_folder):
            matched.append(snap)
        else:
            skipped.append(snap)
    return matched, skipped


def get_snapshot_by_id(vault_path: str, snapshot_id: int) -> Optional[dict]:
    for snap in load_history(vault_path):
        if int(snap.get("timestamp", 0)) == snapshot_id:
            return snap
    return None


def get_snapshot_by_date(vault_path: str, date_str: str) -> Optional[dict]:
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_start = dt.timestamp()
        day_end = day_start + 86400.0
    except ValueError:
        return None
    best_snap = None
    best_delta = None
    for snap in load_history(vault_path):
        ts = snap.get("timestamp", 0)
        if day_start <= ts < day_end:
            delta = abs(ts - (day_start + 43200.0))
            if best_delta is None or delta < best_delta:
                best_delta = delta
                best_snap = snap
    return best_snap


def delete_snapshot(vault_path: str, snapshot_id: int) -> bool:
    path = _snapshot_path(vault_path)
    if not path.exists():
        return False
    snapshots = load_history(vault_path)
    remaining = [s for s in snapshots if int(s.get("timestamp", 0)) != snapshot_id]
    if len(remaining) == len(snapshots):
        return False
    try:
        with path.open("w", encoding="utf-8") as f:
            for s in remaining:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        return True
    except OSError:
        return False


def prune_snapshots(vault_path: str, keep_days: int) -> int:
    path = _snapshot_path(vault_path)
    if not path.exists():
        return 0
    now = time.time()
    cutoff = now - keep_days * 86400.0
    snapshots = load_history(vault_path)
    remaining = [s for s in snapshots if s.get("timestamp", 0) >= cutoff]
    removed = len(snapshots) - len(remaining)
    if removed > 0:
        try:
            with path.open("w", encoding="utf-8") as f:
                for s in remaining:
                    f.write(json.dumps(s, ensure_ascii=False) + "\n")
        except OSError:
            return 0
    return removed


def format_snapshot_summary(snapshot: dict, include_notes: bool = False) -> str:
    ts = snapshot.get("timestamp", 0)
    dt_str = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    snap_id = int(ts)
    filters = snapshot.get("filters", {})
    weights = snapshot.get("heat_weights", {})
    lines: list[str] = []
    lines.append(f"  Snapshot #{snap_id}  ({dt_str})")
    lines.append(f"    Notes: {snapshot.get('total_notes', 0)}  |  Links: {snapshot.get('total_links', 0)}  |  Broken: {snapshot.get('broken_links_count', 0)}")
    tag_list = filters.get("tags", [])
    folder = filters.get("folder", "")
    if tag_list:
        lines.append(f"    Filters: tags={','.join(tag_list)}")
    if folder:
        lines.append(f"    Filters: folder={folder}")
    if not tag_list and not folder:
        lines.append(f"    Filters: (none)")
    lines.append(f"    Weights: inbound={weights.get('w_inbound'):.2f}  tags={weights.get('w_tags'):.2f}  recency={weights.get('w_recency'):.2f}  half_life={weights.get('recency_half_life_days'):.0f}d")
    if include_notes and snapshot.get("notes"):
        lines.append(f"    Top 5 notes by heat_all:")
        note_items = sorted(
            snapshot["notes"].items(),
            key=lambda x: x[1].get("heat_all", 0.0),
            reverse=True,
        )[:5]
        for path_str, nd in note_items:
            title = nd.get("title", Path(path_str).stem)
            heat = nd.get("heat_all", 0.0)
            tags = ",".join(nd.get("tags", []))
            lines.append(f"      [{heat:.3f}] {title}  ({tags})")
    return "\n".join(lines)


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
            "tags": normalize_tags(filter_tags) if filter_tags else [],
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


def collect_earliest_mtimes(
    history_snapshots: list[dict],
    graph: KnowledgeGraph,
) -> dict[str, float]:
    earliest: dict[str, float] = {}
    for snap in history_snapshots:
        for path_str, nd in snap.get("notes", {}).items():
            mtime = nd.get("mtime")
            if mtime is None:
                continue
            if path_str not in earliest or mtime < earliest[path_str]:
                earliest[path_str] = mtime
    for key, note in graph.notes.items():
        if key not in earliest or note.mtime < earliest[key]:
            earliest[key] = note.mtime
    return earliest
