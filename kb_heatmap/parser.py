from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
WIKILINK_STRIP_RE = re.compile(r"\[\[[^\]]+\]\]")
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+.*$", re.MULTILINE)
FENCED_CODE_RE = re.compile(r"```.*?```", re.DOTALL)
INLINE_CODE_RE = re.compile(r"`[^`]*`")
TAG_RE = re.compile(
    r"(?:(?<=^\s)|(?<=\s))"
    r"#([a-zA-Z\u4e00-\u9fff][\w\u4e00-\u9fff\-/]*)"
    r"(?=$|\s|[\.\,\;\!\?\)\"\'\:])",
    re.UNICODE,
)


@dataclass
class LinkInfo:
    raw: str
    target_path: str
    anchor: str
    alias: str
    is_same_page: bool = False

    @property
    def candidate_names(self) -> list[str]:
        names: list[str] = []
        base = self.target_path.strip()
        if base:
            names.append(base)
            p = Path(base)
            stem = str(p.with_suffix("")) if p.suffix else p.stem
            if stem != base:
                names.append(stem)
            parts = base.replace("\\", "/").split("/")
            if len(parts) > 1:
                last = parts[-1]
                names.append(last)
                last_p = Path(last)
                last_stem = str(last_p.with_suffix("")) if last_p.suffix else last_p.stem
                if last_stem != last:
                    names.append(last_stem)
        return names


@dataclass
class BrokenLink:
    source_path: str
    raw_link: str
    target: str


@dataclass
class NoteInfo:
    path: Path
    title: str
    links: list[str] = field(default_factory=list)
    raw_links: list[LinkInfo] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    mtime: float = 0.0
    content_hash: str = ""


def _parse_wikilink(match: str) -> LinkInfo:
    content = match.strip()
    alias = ""
    anchor = ""
    target = content
    is_same_page = False

    if "|" in target:
        target, alias = target.split("|", 1)

    if "#" in target:
        target, anchor = target.split("#", 1)
        if not target.strip():
            is_same_page = True

    return LinkInfo(
        raw=content,
        target_path=target.strip(),
        anchor=anchor.strip(),
        alias=alias.strip(),
        is_same_page=is_same_page,
    )


def _extract_tags(text: str) -> list[str]:
    cleaned = HEADING_RE.sub("", text)
    cleaned = FENCED_CODE_RE.sub("", cleaned)
    cleaned = INLINE_CODE_RE.sub("", cleaned)
    cleaned = WIKILINK_STRIP_RE.sub("", cleaned)
    return TAG_RE.findall(cleaned)


def parse_note(filepath: Path) -> NoteInfo:
    text = filepath.read_text(encoding="utf-8", errors="replace")

    raw_link_matches = WIKILINK_RE.findall(text)
    raw_links = [_parse_wikilink(m) for m in raw_link_matches]
    unique_targets: list[str] = []
    seen_targets: set[str] = set()
    for link in raw_links:
        if link.is_same_page:
            continue
        added = False
        for candidate in link.candidate_names:
            c = candidate.strip()
            if c and c not in seen_targets:
                seen_targets.add(c)
                unique_targets.append(c)
                added = True
                break
        if not added and link.target_path.strip() and link.target_path.strip() not in seen_targets:
            seen_targets.add(link.target_path.strip())
            unique_targets.append(link.target_path.strip())

    tags = _extract_tags(text)
    tags_unique: list[str] = []
    seen_tags: set[str] = set()
    for t in tags:
        tl = t.lower()
        if tl not in seen_tags:
            seen_tags.add(tl)
            tags_unique.append(t)

    stat = filepath.stat()
    mtime = stat.st_mtime

    import hashlib

    content_hash = hashlib.md5(text.encode("utf-8", errors="replace")).hexdigest()

    return NoteInfo(
        path=filepath,
        title=filepath.stem,
        links=unique_targets,
        raw_links=raw_links,
        tags=tags_unique,
        mtime=mtime,
        content_hash=content_hash,
    )
