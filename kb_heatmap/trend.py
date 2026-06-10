from __future__ import annotations

import csv
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .graph import KnowledgeGraph
from .parser import NoteInfo


DAY_SEC = 86400.0


@dataclass
class TrendPoint:
    period: str
    timestamp: float
    heat: float
    in_window: bool
    existed: bool


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
) -> Optional[float]:
    w = graph.heat_weights.normalized()
    half_life_sec = w.recency_half_life_days * DAY_SEC
    max_age_sec = max_age_days * DAY_SEC if max_age_days else None

    if note.mtime > ref_time + 0.001:
        return None

    if max_age_sec is not None and (ref_time - note.mtime) > max_age_sec:
        return None

    sub_inbound: dict[str, int] = {}
    relevant_set: set[str] = set()
    for k, n in graph.notes.items():
        if n.mtime <= ref_time + 0.001:
            if max_age_sec is None or (ref_time - n.mtime) <= max_age_sec:
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

    age_sec = max(ref_time - note.mtime, 0)
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
        pts: list[TrendPoint] = []
        for period_str, ts in periods:
            existed = note.mtime <= ts + 0.001
            snap_heat = _lookup_snapshot(key, note, ts)
            if not existed:
                pts.append(TrendPoint(period=period_str, timestamp=ts, heat=0.0, in_window=False, existed=existed))
            elif snap_heat is not None:
                if hw_days is not None and (ts - note.mtime) > hw_days * DAY_SEC:
                    pts.append(TrendPoint(period=period_str, timestamp=ts, heat=0.0, in_window=False, existed=existed))
                else:
                    pts.append(TrendPoint(period=period_str, timestamp=ts, heat=snap_heat, in_window=True, existed=existed))
            else:
                h = _compute_heat_at(key, note, graph, ts, hw_days)
                if h is None:
                    pts.append(TrendPoint(period=period_str, timestamp=ts, heat=0.0, in_window=False, existed=existed))
                else:
                    pts.append(TrendPoint(period=period_str, timestamp=ts, heat=h, in_window=True, existed=existed))
        series[key] = pts
    return series


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
