from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .parser import NoteInfo, parse_note


@dataclass
class Edge:
    source: str
    target: str


@dataclass
class KnowledgeGraph:
    notes: dict[str, NoteInfo] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)
    inbound_count: dict[str, int] = field(default_factory=dict)
    tag_cooccurrence: dict[str, int] = field(default_factory=dict)
    heat_scores: dict[str, float] = field(default_factory=dict)

    def add_note(self, note: NoteInfo) -> None:
        key = str(note.path)
        self.notes[key] = note

    def resolve_edges(self) -> None:
        self.edges.clear()
        self.inbound_count.clear()
        path_to_key: dict[str, str] = {}
        for key, note in self.notes.items():
            path_to_key[note.path.stem.lower()] = key

        for key, note in self.notes.items():
            for link in note.links:
                target_key = path_to_key.get(link.strip().lower())
                if target_key and target_key != key:
                    self.edges.append(Edge(source=key, target=target_key))
                    self.inbound_count[target_key] = self.inbound_count.get(target_key, 0) + 1

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

    def compute_heat(
        self,
        w_inbound: float = 0.4,
        w_tags: float = 0.3,
        w_recency: float = 0.3,
        recency_half_life_days: float = 90.0,
    ) -> None:
        self.heat_scores.clear()
        now = time.time()
        half_life_sec = recency_half_life_days * 86400.0

        max_inbound = max(self.inbound_count.values()) if self.inbound_count else 1
        max_tag_count = 0
        for note in self.notes.values():
            tc = sum(
                self.tag_cooccurrence.get(tag, 0) for tag in note.tags
            )
            if tc > max_tag_count:
                max_tag_count = tc
        if max_tag_count == 0:
            max_tag_count = 1

        for key, note in self.notes.items():
            inbound_norm = self.inbound_count.get(key, 0) / max_inbound

            tag_score = sum(
                self.tag_cooccurrence.get(tag, 0) for tag in note.tags
            )
            tag_norm = tag_score / max_tag_count

            age_sec = max(now - note.mtime, 0)
            recency_norm = 1.0 / (1.0 + age_sec / half_life_sec)

            heat = (
                w_inbound * inbound_norm
                + w_tags * tag_norm
                + w_recency * recency_norm
            )
            self.heat_scores[key] = heat

    def get_core_hubs(self, top_n: int = 10) -> list[tuple[str, float]]:
        sorted_notes = sorted(self.heat_scores.items(), key=lambda x: x[1], reverse=True)
        return sorted_notes[:top_n]

    def get_isolated_notes(self) -> list[tuple[str, float]]:
        isolated = []
        for key, note in self.notes.items():
            inbound = self.inbound_count.get(key, 0)
            outbound = sum(1 for e in self.edges if e.source == key)
            if inbound == 0 and outbound == 0:
                isolated.append((key, self.heat_scores.get(key, 0.0)))
        isolated.sort(key=lambda x: x[1], reverse=True)
        return isolated

    def filter_by_tags(self, tags: list[str]) -> KnowledgeGraph:
        tags_lower = {t.lower() for t in tags}
        filtered = KnowledgeGraph()
        for key, note in self.notes.items():
            note_tags_lower = {t.lower() for t in note.tags}
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


def build_graph(
    vault_path: str,
    cached_notes: Optional[dict[str, NoteInfo]] = None,
    changed_files: Optional[set[str]] = None,
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

    graph.resolve_edges()
    graph.compute_tag_cooccurrence()
    graph.compute_heat()
    return graph
