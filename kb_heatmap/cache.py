from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .parser import LinkInfo, NoteInfo


CACHE_FILENAME = ".kb_heatmap_cache.json"


def _link_info_to_dict(li: LinkInfo) -> dict:
    return {
        "raw": li.raw,
        "target_path": li.target_path,
        "anchor": li.anchor,
        "alias": li.alias,
    }


def _dict_to_link_info(d: dict) -> LinkInfo:
    return LinkInfo(
        raw=d.get("raw", ""),
        target_path=d.get("target_path", ""),
        anchor=d.get("anchor", ""),
        alias=d.get("alias", ""),
    )


def _note_to_dict(note: NoteInfo) -> dict:
    return {
        "path": str(note.path),
        "title": note.title,
        "links": note.links,
        "raw_links": [_link_info_to_dict(li) for li in note.raw_links],
        "tags": note.tags,
        "mtime": note.mtime,
        "content_hash": note.content_hash,
    }


def _dict_to_note(d: dict) -> NoteInfo:
    raw_links_data = d.get("raw_links", [])
    raw_links = [_dict_to_link_info(rld) for rld in raw_links_data]
    return NoteInfo(
        path=Path(d["path"]),
        title=d["title"],
        links=d["links"],
        raw_links=raw_links,
        tags=d["tags"],
        mtime=d["mtime"],
        content_hash=d["content_hash"],
    )


def load_cache(vault_path: str) -> Optional[dict[str, NoteInfo]]:
    cache_path = Path(vault_path).resolve() / CACHE_FILENAME
    if not cache_path.exists():
        return None
    try:
        data = json.loads(cache_path.read_text(encoding="utf-8"))
        return {k: _dict_to_note(v) for k, v in data.get("notes", {}).items()}
    except (json.JSONDecodeError, KeyError, TypeError):
        return None


def save_cache(vault_path: str, notes: dict[str, NoteInfo]) -> None:
    cache_path = Path(vault_path).resolve() / CACHE_FILENAME
    data = {
        "notes": {k: _note_to_dict(v) for k, v in notes.items()},
    }
    cache_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def detect_changes(vault_path: str, cached_notes: dict[str, NoteInfo]) -> set[str]:
    from .parser import parse_note

    vault = Path(vault_path).resolve()
    changed: set[str] = set()
    current_files: set[str] = set()

    for md in vault.rglob("*.md"):
        key = str(md)
        current_files.add(key)
        if key not in cached_notes:
            changed.add(key)
        else:
            cached = cached_notes[key]
            current = parse_note(md)
            if current.content_hash != cached.content_hash:
                changed.add(key)

    for key in set(cached_notes.keys()) - current_files:
        changed.add(key)

    return changed
