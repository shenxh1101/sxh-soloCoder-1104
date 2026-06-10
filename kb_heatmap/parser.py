from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


WIKILINK_RE = re.compile(r"\[\[([^\]|]+?)(?:\|[^\]]+?)?\]\]")
TAG_RE = re.compile(r"(?:^|\s)#([a-zA-Z\u4e00-\u9fff][\w\u4e00-\u9fff\-/]*)", re.UNICODE)


@dataclass
class NoteInfo:
    path: Path
    title: str
    links: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    mtime: float = 0.0
    content_hash: str = ""

    def resolve_link_target(self, link: str, all_notes: dict[str, NoteInfo]) -> Optional[str]:
        stem = link.strip()
        for key, note in all_notes.items():
            if note.title == stem or note.path.stem == stem:
                return key
        for key, note in all_notes.items():
            if note.path.stem.lower() == stem.lower():
                return key
        return None


def parse_note(filepath: Path) -> NoteInfo:
    text = filepath.read_text(encoding="utf-8", errors="replace")
    links = list(dict.fromkeys(WIKILINK_RE.findall(text)))
    tags = list(dict.fromkeys(TAG_RE.findall(text)))
    tags_lower = []
    seen = set()
    for t in tags:
        tl = t.lower()
        if tl not in seen:
            seen.add(tl)
            tags_lower.append(t)

    stat = filepath.stat()
    mtime = stat.st_mtime

    import hashlib

    content_hash = hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()

    return NoteInfo(
        path=filepath,
        title=filepath.stem,
        links=links,
        tags=tags_lower,
        mtime=mtime,
        content_hash=content_hash,
    )
