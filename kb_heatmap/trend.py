from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .graph import KnowledgeGraph
from .history import collect_earliest_mtimes
from .parser import NoteInfo


DAY_SEC = 86400.0


@dataclass
class TrendPoint:
    period: str
    timestamp: float
    heat: float
    in_window: bool
    existed: bool


@dataclass
class TrendDiffResult:
    from_snapshot: Optional[dict]
    to_snapshot: Optional[dict]
    from_time: float
    to_time: float
    gained: list[tuple[str, float, float]] = field(default_factory=list)
    lost: list[tuple[str, float, float]] = field(default_factory=list)
    new_notes: list[tuple[str, float]] = field(default_factory=list)
    removed_notes: list[tuple[str, float]] = field(default_factory=list)
    unchanged: list[tuple[str, float, float]] = field(default_factory=list)
    all_changes: list[dict] = field(default_factory=list)


def _day_key(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y-%m-%d")


def _week_key(ts: float) -> str:
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    iso_year, iso_week, _ = dt.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def _parse_window(window: Optional[str]) -> Optional[float]:
    if window is None or window == "all":
        return None
    if window == "7d":
        return 7.0
    if window == "30d":
        return 30.0
    try:
        return float(window.rstrip("d"))
    except (ValueError, AttributeError):
        return None


def _compute_heat_at(
    note_key: str,
    note: NoteInfo,
    graph: KnowledgeGraph,
    ref_time: float,
    max_age_days: Optional[float],
    earliest_mtime_by_path: Optional[dict[str, float]] = None,
) -> Optional[float]:
    w = graph.heat_weights.normalized()
    half_life_sec = w.recency_half_life_days * DAY_SEC
    max_age_sec = max_age_days * DAY_SEC if max_age_days else None

    path_key = str(note.path)
    effective_mtime = note.mtime
    if earliest_mtime_by_path and path_key in earliest_mtime_by_path:
        effective_mtime = earliest_mtime_by_path[path_key]

    if effective_mtime > ref_time + 0.001:
        return None

    if max_age_sec is not None and (ref_time - effective_mtime) > max_age_sec:
        return None

    sub_inbound: dict[str, int] = {}
    relevant_set: set[str] = set()
    for k, n in graph.notes.items():
        nk = str(n.path)
        em = n.mtime
        if earliest_mtime_by_path and nk in earliest_mtime_by_path:
            em = earliest_mtime_by_path[nk]
        if em <= ref_time + 0.001:
            if max_age_sec is None or (ref_time - em) <= max_age_sec:
                relevant_set.add(k)
    for edge in graph.edges:
        if edge.source in relevant_set and edge.target in relevant_set:
            sub_inbound[edge.target] = sub_inbound.get(edge.target, 0) + 1

    max_inbound = max(sub_inbound.values()) if sub_inbound else 1
    if max_inbound == 0:
        max_inbound = 1

    max_tag_count = 0
    for k in relevant_set:
        n = graph.notes[k]
        tc = sum(graph.tag_cooccurrence.get(tag, 0) for tag in n.tags)
        if tc > max_tag_count:
            max_tag_count = tc
    if max_tag_count == 0:
        max_tag_count = 1

    if note_key not in relevant_set:
        return None

    inbound_norm = sub_inbound.get(note_key, 0) / max_inbound

    tag_score = sum(graph.tag_cooccurrence.get(tag, 0) for tag in note.tags)
    tag_norm = tag_score / max_tag_count

    age_sec = max(ref_time - effective_mtime, 0)
    recency_norm = 1.0 / (1.0 + age_sec / half_life_sec)

    return (
        w.w_inbound * inbound_norm
        + w.w_tags * tag_norm
        + w.w_recency * recency_norm
    )


def generate_trend_series(
    graph: KnowledgeGraph,
    period: str = "daily",
    window_days: int = 90,
    heat_window: Optional[str] = None,
    history_snapshots: Optional[list[dict]] = None,
) -> dict[str, list[TrendPoint]]:
    now = time.time()
    period_fn = _week_key if period == "weekly" else _day_key
    step = 7 * DAY_SEC if period == "weekly" else DAY_SEC
    hw_days = _parse_window(heat_window)

    periods: list[tuple[str, float]] = []
    t = now - (window_days - 1) * DAY_SEC
    while t <= now:
        periods.append((period_fn(t), t))
        t += step

    earliest_mtime_by_path = collect_earliest_mtimes(history_snapshots or [], graph)

    snap_heat_by_path: dict[str, dict[float, float]] = {}
    if history_snapshots:
        for snap in history_snapshots:
            ts = snap.get("timestamp")
            if not ts:
                continue
            hw_field = {
                "7d": "heat_7d",
                "30d": "heat_30d",
                "all": "heat_all",
                None: "heat_all",
            }[heat_window]
            for path_str, nd in snap.get("notes", {}).items():
                heat = nd.get(hw_field, 0.0)
                if path_str not in snap_heat_by_path:
                    snap_heat_by_path[path_str] = {}
                snap_heat_by_path[path_str][ts] = heat

    def _lookup_snapshot(key: str, note: NoteInfo, ts: float) -> Optional[float]:
        path_str = str(note.path)
        by_ts = snap_heat_by_path.get(path_str)
        if not by_ts:
            return None
        best_ts: Optional[float] = None
        for snap_ts in by_ts:
            if snap_ts <= ts + 0.001:
                if best_ts is None or abs(snap_ts - ts) < abs(best_ts - ts):
                    best_ts = snap_ts
        if best_ts is None:
            return None
        if abs(best_ts - ts) > 1.5 * step:
            return None
        return by_ts[best_ts]

    series: dict[str, list[TrendPoint]] = {}
    for key, note in graph.notes.items():
        path_key = str(note.path)
        effective_mtime = earliest_mtime_by_path.get(path_key, note.mtime)
        pts: list[TrendPoint] = []
        for period_str, ts in periods:
            existed = effective_mtime <= ts + 0.001
            snap_heat = _lookup_snapshot(key, note, ts)
            if not existed:
                pts.append(TrendPoint(period=period_str, timestamp=ts, heat=0.0, in_window=False, existed=existed))
            elif snap_heat is not None:
                if hw_days is not None and (ts - effective_mtime) > hw_days * DAY_SEC:
                    pts.append(TrendPoint(period=period_str, timestamp=ts, heat=0.0, in_window=False, existed=existed))
                else:
                    pts.append(TrendPoint(period=period_str, timestamp=ts, heat=snap_heat, in_window=True, existed=existed))
            else:
                h = _compute_heat_at(key, note, graph, ts, hw_days, earliest_mtime_by_path)
                if h is None:
                    pts.append(TrendPoint(period=period_str, timestamp=ts, heat=0.0, in_window=False, existed=existed))
                else:
                    pts.append(TrendPoint(period=period_str, timestamp=ts, heat=h, in_window=True, existed=existed))
        series[key] = pts
    return series


def generate_trend_diff(
    from_snapshot: dict,
    to_snapshot: dict,
    heat_window: str = "all",
) -> TrendDiffResult:
    hw_field = {
        "7d": "heat_7d",
        "30d": "heat_30d",
        "all": "heat_all",
    }[heat_window]

    from_ts = from_snapshot.get("timestamp", 0)
    to_ts = to_snapshot.get("timestamp", 0)
    from_notes = from_snapshot.get("notes", {})
    to_notes = to_snapshot.get("notes", {})

    from_paths = set(from_notes.keys())
    to_paths = set(to_notes.keys())

    gained: list[tuple[str, float, float]] = []
    lost: list[tuple[str, float, float]] = []
    unchanged: list[tuple[str, float, float]] = []
    new_notes: list[tuple[str, float]] = []
    removed_notes: list[tuple[str, float]] = []
    all_changes: list[dict] = []

    common = from_paths & to_paths
    for path_str in common:
        fn = from_notes[path_str]
        tn = to_notes[path_str]
        fh = fn.get(hw_field, 0.0)
        th = tn.get(hw_field, 0.0)
        delta = th - fh
        change = {
            "path": path_str,
            "title": tn.get("title", Path(path_str).stem),
            "tags": tn.get("tags", []),
            "heat_from": fh,
            "heat_to": th,
            "delta": delta,
            "change_type": "gained" if delta > 1e-6 else ("lost" if delta < -1e-6 else "unchanged"),
        }
        all_changes.append(change)
        if delta > 1e-6:
            gained.append((path_str, fh, th))
        elif delta < -1e-6:
            lost.append((path_str, fh, th))
        else:
            unchanged.append((path_str, fh, th))

    for path_str in to_paths - from_paths:
        tn = to_notes[path_str]
        th = tn.get(hw_field, 0.0)
        new_notes.append((path_str, th))
        all_changes.append({
            "path": path_str,
            "title": tn.get("title", Path(path_str).stem),
            "tags": tn.get("tags", []),
            "heat_from": 0.0,
            "heat_to": th,
            "delta": th,
            "change_type": "new",
        })

    for path_str in from_paths - to_paths:
        fn = from_notes[path_str]
        fh = fn.get(hw_field, 0.0)
        removed_notes.append((path_str, fh))
        all_changes.append({
            "path": path_str,
            "title": fn.get("title", Path(path_str).stem),
            "tags": fn.get("tags", []),
            "heat_from": fh,
            "heat_to": 0.0,
            "delta": -fh,
            "change_type": "removed",
        })

    gained.sort(key=lambda x: x[2] - x[1], reverse=True)
    lost.sort(key=lambda x: x[1] - x[2], reverse=True)
    new_notes.sort(key=lambda x: x[1], reverse=True)
    removed_notes.sort(key=lambda x: x[1], reverse=True)
    all_changes.sort(key=lambda x: x["delta"], reverse=True)

    return TrendDiffResult(
        from_snapshot=from_snapshot,
        to_snapshot=to_snapshot,
        from_time=from_ts,
        to_time=to_ts,
        gained=gained,
        lost=lost,
        new_notes=new_notes,
        removed_notes=removed_notes,
        unchanged=unchanged,
        all_changes=all_changes,
    )


def export_trend_diff_csv(
    diff: TrendDiffResult,
    output_path: str,
    graph: Optional[KnowledgeGraph] = None,
) -> list[list[str]]:
    rows: list[list[str]] = []
    header = ["change_type", "title", "path", "tags", "heat_from", "heat_to", "delta"]
    rows.append(header)
    for c in diff.all_changes:
        rows.append([
            c["change_type"],
            c["title"],
            c["path"],
            ",".join(c["tags"]),
            f"{c['heat_from']:.6f}",
            f"{c['heat_to']:.6f}",
            f"{c['delta']:.6f}",
        ])
    out = Path(output_path)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return rows


def render_trend_diff_text(
    diff: TrendDiffResult,
    top_n: int = 10,
) -> str:
    lines: list[str] = []
    from_dt = datetime.fromtimestamp(diff.from_time).strftime("%Y-%m-%d %H:%M:%S")
    to_dt = datetime.fromtimestamp(diff.to_time).strftime("%Y-%m-%d %H:%M:%S")
    lines.append("")
    lines.append(f"  📊 Heat Trend Diff")
    lines.append(f"  {'─' * 60}")
    lines.append(f"  From: {from_dt}")
    lines.append(f"  To:   {to_dt}")
    lines.append(f"  {'─' * 60}")

    from .heatmap import SIMPLE_PALETTE, _supports_256_color
    use_color = _supports_256_color()

    def _fmt_path(path_str: str) -> str:
        if diff.from_snapshot and path_str in diff.from_snapshot.get("notes", {}):
            return diff.from_snapshot["notes"][path_str].get("title", Path(path_str).stem)
        if diff.to_snapshot and path_str in diff.to_snapshot.get("notes", {}):
            return diff.to_snapshot["notes"][path_str].get("title", Path(path_str).stem)
        return Path(path_str).stem

    GREEN = "\033[92m"
    RED = "\033[91m"
    YELLOW = "\033[93m"
    RESET = "\033[0m"

    if diff.new_notes:
        lines.append(f"  {GREEN}✨ New Notes{RESET}")
        for path_str, th in diff.new_notes[:top_n]:
            title = _fmt_path(path_str)
            lines.append(f"    + [{th:.3f}] {title}")
        lines.append("")

    if diff.removed_notes:
        lines.append(f"  {RED}🗑️  Removed Notes{RESET}")
        for path_str, fh in diff.removed_notes[:top_n]:
            title = _fmt_path(path_str)
            lines.append(f"    - [{fh:.3f}] {title}")
        lines.append("")

    if diff.gained:
        lines.append(f"  {GREEN}🔥 Heat Gained{RESET}")
        for path_str, fh, th in diff.gained[:top_n]:
            title = _fmt_path(path_str)
            delta = th - fh
            lines.append(f"    ↑ [{fh:.3f} → {th:.3f}] (+{delta:.3f}) {title}")
        lines.append("")

    if diff.lost:
        lines.append(f"  {RED}📉 Heat Lost{RESET}")
        for path_str, fh, th in diff.lost[:top_n]:
            title = _fmt_path(path_str)
            delta = fh - th
            lines.append(f"    ↓ [{fh:.3f} → {th:.3f}] (-{delta:.3f}) {title}")
        lines.append("")

    total_common = len(diff.gained) + len(diff.lost) + len(diff.unchanged)
    lines.append(f"  {YELLOW}Summary: +{len(diff.new_notes)} new, -{len(diff.removed_notes)} removed, {len(diff.gained)} ↑, {len(diff.lost)} ↓, {len(diff.unchanged)} stable (of {total_common} common notes){RESET}")
    lines.append("")
    return "\n".join(lines)


def export_trend_csv(
    graph: KnowledgeGraph,
    output_path: str,
    period: str = "daily",
    window_days: int = 90,
    heat_window: Optional[str] = None,
    mark_absence: bool = True,
    absence_value: str = "",
    history_snapshots: Optional[list[dict]] = None,
) -> list[list[str]]:
    series = generate_trend_series(graph, period, window_days, heat_window, history_snapshots)
    if not series:
        return []

    sample_key = next(iter(series))
    periods = [p.period for p in series[sample_key]]

    rows: list[list[str]] = []
    header = ["title", "path", "tags"] + periods
    rows.append(header)

    for key, note in graph.notes.items():
        pts = series.get(key, [])
        heat_vals: list[str] = []
        for p in pts:
            if not p.existed:
                heat_vals.append(absence_value)
            elif mark_absence and not p.in_window:
                heat_vals.append(absence_value)
            else:
                heat_vals.append(f"{p.heat:.6f}")
        rows.append([
            note.title,
            str(note.path),
            ",".join(note.tags),
            *heat_vals,
        ])

    out = Path(output_path)
    with out.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)
    return rows


def render_trend_text(
    graph: KnowledgeGraph,
    period: str = "daily",
    window_days: int = 14,
    top_n: int = 8,
    heat_window: Optional[str] = None,
    history_snapshots: Optional[list[dict]] = None,
    skipped_snapshots: Optional[list[dict]] = None,
) -> str:
    from .heatmap import SIMPLE_PALETTE, _supports_256_color

    series = generate_trend_series(graph, period, window_days, heat_window, history_snapshots)
    if not series:
        return "(no data)"

    avg_series: dict[str, float] = {}
    for key, pts in series.items():
        vals = [p.heat for p in pts if p.in_window and p.existed]
        avg_series[key] = sum(vals) / len(vals) if vals else 0.0

    top_keys = sorted(avg_series, key=avg_series.get, reverse=True)[:top_n]
    if not top_keys:
        return "(no notes in range)"

    lines: list[str] = []
    lines.append("")
    lines.append(f"  📈 Heat Trend — {period.capitalize()} ({window_days} days)")
    if heat_window:
        lines.append(f"  Heat window: {heat_window}")
    if history_snapshots:
        lines.append(f"  Using {len(history_snapshots)} historical snapshot(s) for real trend data")
    if skipped_snapshots:
        lines.append(f"  ⚠️  Skipped {len(skipped_snapshots)} snapshot(s) due to mismatched filters/weights:")
        for s in skipped_snapshots[:5]:
            ts = s.get("timestamp", 0)
            dt = datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
            f = s.get("filters", {})
            w = s.get("heat_weights", {})
            reason_parts = []
            if f.get("tags"):
                reason_parts.append(f"tags={','.join(f['tags'])}")
            if f.get("folder"):
                reason_parts.append(f"folder={f['folder']}")
            reason_parts.append(f"weights={w.get('w_inbound',0):.2f}/{w.get('w_tags',0):.2f}/{w.get('w_recency',0):.2f}")
            lines.append(f"     · #{int(ts)} ({dt})  [{', '.join(reason_parts)}]")
        if len(skipped_snapshots) > 5:
            lines.append(f"     · ... and {len(skipped_snapshots) - 5} more")
    lines.append(f"  {'─' * 60}")

    use_color = _supports_256_color()

    def color_cell(val: float, in_w: bool, existed: bool) -> str:
        if not existed:
            return " ×" if use_color else " x"
        if not in_w:
            return " ·" if use_color else " ."
        idx = int(val * (len(SIMPLE_PALETTE) - 1))
        idx = max(0, min(idx, len(SIMPLE_PALETTE) - 1))
        r, g, b = SIMPLE_PALETTE[idx]
        if use_color:
            return f"\033[48;2;{r};{g};{b}m  \033[0m"
        else:
            chars = " ░▒▓█"
            ci = int(val * (len(chars) - 1))
            return chars[ci] * 2

    for key in top_keys:
        note = graph.notes.get(key)
        title = note.title if note else Path(key).stem
        pts = series[key]
        cells = [color_cell(p.heat, p.in_window, p.existed) for p in pts]
        lines.append(f"  {title[:30]:<30}  " + "".join(cells))

    period_labels = [p.period for p in series[top_keys[0]]]
    if period_labels:
        step = max(1, len(period_labels) // 10)
        shown_labels = [period_labels[i] if i % step == 0 else "" for i in range(len(period_labels))]
        label_str = "   ".join(s.ljust(2) for s in shown_labels)
        lines.append(f"  {'':30}  {label_str}")

    legend_cells = [color_cell(i / 9.0, True, True) for i in range(10)]
    lines.append(f"  {'':30}  Legend: " + "".join(legend_cells) + " Low→High  (·=out of window, ×=not existed yet)")
    lines.append("")
    return "\n".join(lines)
