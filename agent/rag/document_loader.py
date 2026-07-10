#!/usr/bin/env python3
"""Load Markdown knowledge-base documents and split them into RAG chunks."""

from __future__ import annotations

import argparse
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_KNOWLEDGE_BASE = REPO_ROOT / "knowledge-base"
DEFAULT_CHUNK_SIZE = 900
DEFAULT_OVERLAP = 120
MIN_CHUNK_SIZE = 180


@dataclass
class MarkdownSection:
    heading: str
    content: str


def load_chunks(
    knowledge_base: str | Path = DEFAULT_KNOWLEDGE_BASE,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int = DEFAULT_OVERLAP,
) -> list[dict[str, Any]]:
    base = resolve_path(knowledge_base)
    chunks: list[dict[str, Any]] = []
    for path in sorted(base.rglob("*.md")):
        if ".index" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        title = extract_title(text, path)
        category = category_for(path)
        document_id = str(path.relative_to(base)).replace("\\", "/")
        sections = split_markdown_sections(text)
        index = 0
        pending_short = ""
        pending_heading = ""
        for section in sections:
            for raw_chunk in split_text(section.content, chunk_size, overlap):
                content = raw_chunk.strip()
                if not content:
                    continue
                heading = section.heading or title
                if len(content) < MIN_CHUNK_SIZE:
                    pending_short = (pending_short + "\n\n" + content).strip()
                    pending_heading = pending_heading or heading
                    if len(pending_short) < MIN_CHUNK_SIZE:
                        continue
                    content = pending_short
                    heading = pending_heading
                    pending_short = ""
                    pending_heading = ""
                chunks.append(
                    {
                        "documentId": document_id,
                        "sourcePath": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                        "title": title,
                        "category": category,
                        "heading": heading,
                        "chunkId": f"{document_id}#chunk-{index}",
                        "content": content,
                    }
                )
                index += 1
        if pending_short:
            chunks.append(
                {
                    "documentId": document_id,
                    "sourcePath": str(path.relative_to(REPO_ROOT)).replace("\\", "/"),
                    "title": title,
                    "category": category,
                    "heading": pending_heading or title,
                    "chunkId": f"{document_id}#chunk-{index}",
                    "content": pending_short,
                }
            )
    return chunks


def source_file_hashes(knowledge_base: str | Path = DEFAULT_KNOWLEDGE_BASE) -> dict[str, str]:
    base = resolve_path(knowledge_base)
    hashes = {}
    for path in sorted(base.rglob("*.md")):
        if ".index" in path.parts:
            continue
        rel = str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        hashes[rel] = hashlib.sha256(path.read_bytes()).hexdigest()
    return hashes


def split_markdown_sections(text: str) -> list[MarkdownSection]:
    lines = text.splitlines()
    sections: list[MarkdownSection] = []
    current_heading = ""
    current_lines: list[str] = []
    for line in lines:
        heading_match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading_match and current_lines:
            sections.append(MarkdownSection(current_heading, "\n".join(current_lines).strip()))
            current_lines = [line]
            current_heading = heading_match.group(2).strip()
        else:
            if heading_match and not current_heading:
                current_heading = heading_match.group(2).strip()
            current_lines.append(line)
    if current_lines:
        sections.append(MarkdownSection(current_heading, "\n".join(current_lines).strip()))
    return sections or [MarkdownSection("", text)]


def split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    clean = text.strip()
    if len(clean) <= chunk_size:
        return [clean]
    chunks = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + chunk_size)
        if end < len(clean):
            boundary = max(clean.rfind("\n\n", start, end), clean.rfind("\n", start, end), clean.rfind(". ", start, end))
            if boundary > start + chunk_size // 2:
                end = boundary + 1
        chunks.append(clean[start:end].strip())
        if end >= len(clean):
            break
        start = max(end - overlap, start + 1)
    return chunks


def extract_title(text: str, path: Path) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return path.stem


def category_for(path: Path) -> str:
    parts = set(path.parts)
    if "troubleshooting" in parts:
        return "troubleshooting"
    if "examples" in parts:
        return "example"
    return "guide"


def resolve_path(path: str | Path) -> Path:
    value = Path(path)
    if not value.is_absolute():
        value = REPO_ROOT / value
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Load and chunk Markdown knowledge-base documents.")
    parser.add_argument("--knowledge-base", default=str(DEFAULT_KNOWLEDGE_BASE))
    parser.add_argument("--chunk-size", type=int, default=DEFAULT_CHUNK_SIZE)
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    args = parser.parse_args()
    chunks = load_chunks(args.knowledge_base, args.chunk_size, args.overlap)
    for chunk in chunks:
        print(f"{chunk['chunkId']} :: {chunk['sourcePath']} :: {len(chunk['content'])} chars")
    print(f"chunks={len(chunks)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
