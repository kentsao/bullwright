"""Report-body chunker (docs/ARCHITECTURE.md §6).

One chunk per body section by default; long sections split at sentence
boundaries around `target_chars`. Chunks carry section metadata so search
hits cite `report_id#section` precisely.
"""

import re
from dataclasses import dataclass
from typing import Any

TARGET_CHARS = 1200
MAX_CHARS = 2000

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class Chunk:
    section: str
    seq: int
    text: str


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    parts: list[str] = []
    current = ""
    for sentence in _SENTENCE_END.split(text):
        if current and len(current) + len(sentence) > TARGET_CHARS:
            parts.append(current.strip())
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current.strip():
        parts.append(current.strip())
    return parts


def chunk_report_body(body: dict[str, Any]) -> list[Chunk]:
    chunks: list[Chunk] = []
    seq = 0
    for section, value in body.items():
        texts = [str(v) for v in value] if isinstance(value, list) else [str(value)]
        for text in texts:
            for piece in _split_long(text):
                if len(piece.strip()) < 20:  # too short to be a useful hit
                    continue
                chunks.append(Chunk(section=section, seq=seq, text=piece.strip()))
                seq += 1
    return chunks
