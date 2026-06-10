from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .parser import BrokenLink, LinkInfo, NoteInfo, parse_note


def normalize_tag(tag: str) -> str:
    t = tag.strip().lstrip("#")
    return t.lower()


def normalize_tags(tags: list[str]) -> list[str]:
    return [normalize_tag(t) for t in tags if t and t.strip()]


@dataclass
class Edge:
    source: str
    target: str


def _fuzzy_match(link_target: str, note_title: str) -> bool:
    lt = link_target.strip().lower()
    nt = note_title.strip().lower()
    if not lt or not nt:
        return False
    if lt == nt:
        return True
    if lt in nt or nt in lt:
        return True
    lt_words = set(lt.replace("-", " ").replace("_", " ").split())
    nt_words = set(nt.replace("-", " ").replace("_", " ").split())
    if lt_words and nt_words:
        overlap = len(lt_words & nt_words)
        if overlap >= len(lt_words) * 0.5 and overlap >= 1:
            return True
    return False


@dataclass
class KnowledgeGraph:
    notes: dict[str, NoteInfo] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    inbound_count: dict[str, int] = field(default_factory=dict)
    tag_cooccurrence: dict[str, int] = field(default_factory=dict)
    heat_scores: dict[str, float] = field(default_factory=dict)
    heat_scores_7d: dict[str, float] = field(default_factory=dict)
    heat_scores_30d: dict[str, float] = field(default_factory=dict)
    heat_scores_all: dict[str, float] = field(default_factory=dict)
    broken_links: list[BrokenLink] = field(default_factory=list)

    def add_note(self, note: NoteInfo) -> None:
        key = str(note.path)
        self.notes[key] = note

    def _build_lookup_tables(self) -> dict[str, str]:
        path_to_key: dict[str, str] = {}
        for key, note in self.notes.items():
            stem = note.path.stem
            stem_lower = stem.lower()
            path_to_key.setdefault(stem_lower, key)
            path_to_key.setdefault(stem, key)
            title_lower = note.title.lower()
            path_to_key.setdefault(title_lower, key)
            path_to_key.setdefault(note.title, key)

            try:
                vault_root = note.path.parent.parent
                if vault_root:
                    rel = note.path.relative_to(vault_root.parent if vault_root.parent != vault_root else note.path.parent)
            except (ValueError, OSError):
                pass

            for k2, n2 in self.notes.items():
                try:
                    common = note.path.parent
                    rel = n2.path.relative_to(common)
                    rel_stem = str(rel.with_suffix("")).replace("\\", "/")
                    path_to_key.setdefault(rel_stem.lower(), k2)
                    path_to_key.setdefault(rel_stem, k2)
                except ValueError:
                    pass
            try:
                parts = note.path.relative_to(note.path.parent.parent if note.path.parent.parent and note.path.parent.parent != note.path.parent else note.path.parent)
                rel_str = str(parts.with_suffix("")).replace("\\", "/")
                path_to_key.setdefault(rel_str.lower(), key)
                path_to_key.setdefault(rel_str, key)
            except (ValueError, OSError):
                pass
        return path_to_key

    def _resolve_link(self, raw_link: LinkInfo) -> Optional[str]:
        if raw_link.is_same_page:
            return "__self__"
        candidates = list(dict.fromkeys([c.strip() for c in raw_link.candidate_names if c.strip()]))
        if not candidates and raw_link.target_path.strip():
            candidates = [raw_link.target_path.strip()]
        if not candidates:
            return None

        path_to_key = self._build_lookup_tables()
        for c in candidates:
            c_lower = c.lower()
            if c in path_to_key:
                return path_to_key[c]
            if c_lower in path_to_key:
                return path_to_key[c_lower]

        for c in candidates:
            for key, note in self.notes.items():
                if _fuzzy_match(c, note.title) or _fuzzy_match(c, note.path.stem):
                    return key

        return None

    def resolve_edges(self) -> None:
        self.edges.clear()
        self.inbound_count.clear()
        self.broken_links.clear()

        for key, note in self.notes.items():
            seen_targets_for_note: set[tuple[str, str]] = set()
            for raw_link in note.raw_links:
                resolved = self._resolve_link(raw_link)
                if resolved == "__self__":
                    continue
                if resolved and resolved != key:
                    pair = (key, resolved)
                    if pair not in seen_targets_for_note:
                        seen_targets_for_note.add(pair)
                        self.edges.append(Edge(source=key, target=resolved))
                        self.inbound_count[resolved] = self.inbound_count.get(resolved, 0) + 1
                elif not resolved:
                    target = raw_link.target_path or raw_link.raw
                    self.broken_links.append(
                        BrokenLink(
                            source_path=key,
                            raw_link=raw_link.raw,
                            target=target,
                        )
                    )

    def compute_tag_cooccurrence(self) -> None:
        self.tag_cooccurrence.clear()
        for key, note in self.notes.items():
            count = len(note.tags)
            for tag in note.tags:
                self.tag_cooccurrence[tag] = self.tag_cooccurrence.get(tag, 0) + 1
            if count > 1:
                for i in range(len(note.tags)):
                    for j in range(i + 1, len(note.tags)):
                        pair = tuple(sorted([note.tags[i], note.tags[j]]))
                        pair_key = f"{pair[0]}|{pair[1]}"
                        self.tag_cooccurrence[pair_key] = self.tag_cooccurrence.get(pair_key, 0) + 1

    def _compute_heat_for_window(
        self,
        max_age_days: Optional[float],
        w_inbound: float = 0.4,
        w_tags: float = 0.3,
        w_recency: float = 0.3,
        recency_half_life_days: float = 90.0,
    ) -> dict[str, float]:
        scores: dict[str, float] = {}
        now = time.time()
        half_life_sec = recency_half_life_days * 86400.0
        max_age_sec = max_age_days * 86400.0 if max_age_days else None

        relevant_notes: list[str] = []
        for key, note in self.notes.items():
            if max_age_sec is None or (now - note.mtime) <= max_age_sec:
                relevant_notes.append(key)

        if not relevant_notes:
            return {}

        sub_inbound: dict[str, int] = {}
        for edge in self.edges:
            if edge.source in relevant_notes and edge.target in relevant_notes:
                sub_inbound[edge.target] = sub_inbound.get(edge.target, 0) + 1

        max_inbound = max(sub_inbound.values()) if sub_inbound else 1
        if max_inbound == 0:
            max_inbound = 1

        max_tag_count = 0
        for key in relevant_notes:
            note = self.notes[key]
            tc = sum(self.tag_cooccurrence.get(tag, 0) for tag in note.tags)
            if tc > max_tag_count:
                max_tag_count = tc
        if max_tag_count == 0:
            max_tag_count = 1

        for key in relevant_notes:
            note = self.notes[key]
            inbound_norm = sub_inbound.get(key, 0) / max_inbound

            tag_score = sum(self.tag_cooccurrence.get(tag, 0) for tag in note.tags)
            tag_norm = tag_score / max_tag_count

            age_sec = max(now - note.mtime, 0)
            recency_norm = 1.0 / (1.0 + age_sec / half_life_sec)

            heat = (
                w_inbound * inbound_norm
                + w_tags * tag_norm
                + w_recency * recency_norm
            )
            scores[key] = heat
        return scores

    def compute_heat(self) -> None:
        self.heat_scores_7d = self._compute_heat_for_window(7)
        self.heat_scores_30d = self._compute_heat_for_window(30)
        self.heat_scores_all = self._compute_heat_for_window(None)
        self.heat_scores = self.heat_scores_all

    def get_core_hubs(
        self, top_n: int = 10, window: str = "all"
    ) -> list[tuple[str, float]]:
        if window == "7d":
            scores = self.heat_scores_7d
        elif window == "30d":
            scores = self.heat_scores_30d
        else:
            scores = self.heat_scores_all
        sorted_notes = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_notes[:top_n]

    def get_isolated_notes(self) -> list[tuple[str, float]]:
        isolated = []
        for key, note in self.notes.items():
            inbound = self.inbound_count.get(key, 0)
            outbound = sum(1 for e in self.edges if e.source == key)
            if inbound == 0 and outbound == 0:
                isolated.append((key, self.heat_scores_all.get(key, 0.0)))
        isolated.sort(key=lambda x: x[1], reverse=True)
        return isolated

    def filter_by_tags(self, tags: list[str]) -> KnowledgeGraph:
        tags_lower = set(normalize_tags(tags))
        filtered = KnowledgeGraph()
        for key, note in self.notes.items():
            note_tags_lower = {normalize_tag(t) for t in note.tags}
            if note_tags_lower & tags_lower:
                filtered.notes[key] = note
        filtered.resolve_edges()
        filtered.compute_tag_cooccurrence()
        filtered.compute_heat()
        return filtered

    def filter_by_folder(self, folder: str) -> KnowledgeGraph:
        folder_path = Path(folder).resolve()
        filtered = KnowledgeGraph()
        for key, note in self.notes.items():
            try:
                note_path = note.path.resolve()
                if folder_path in note_path.parents or note_path == folder_path:
                    filtered.notes[key] = note
            except (ValueError, OSError):
                pass
        filtered.resolve_edges()
        filtered.compute_tag_cooccurrence()
        filtered.compute_heat()
        return filtered

    def refresh_mtimes(self) -> None:
        for key, note in self.notes.items():
            try:
                note.mtime = note.path.stat().st_mtime
            except OSError:
                pass


def build_graph(
    vault_path: str,
    cached_notes: Optional[dict[str, NoteInfo]] = None,
    changed_files: Optional[set[str]] = None,
    refresh_mtimes: bool = True,
) -> KnowledgeGraph:
    vault = Path(vault_path).resolve()
    graph = KnowledgeGraph()

    all_md_files: dict[str, Path] = {}
    for md in vault.rglob("*.md"):
        all_md_files[str(md)] = md

    if cached_notes is not None and changed_files is not None:
        for key, note in cached_notes.items():
            if key not in all_md_files:
                continue
            if key in changed_files:
                note = parse_note(all_md_files[key])
            graph.notes[key] = note
        for key in set(all_md_files.keys()) - set(cached_notes.keys()):
            note = parse_note(all_md_files[key])
            graph.notes[key] = note
    else:
        for key, filepath in all_md_files.items():
            note = parse_note(filepath)
            graph.notes[key] = note

    if refresh_mtimes:
        graph.refresh_mtimes()

    graph.resolve_edges()
    graph.compute_tag_cooccurrence()
    graph.compute_heat()
    return graph
