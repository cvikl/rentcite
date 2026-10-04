"""Corpus loading, chunking and verbatim quote slicing.

A document is the raw text file from the starter pack. Chunks are numbered paragraphs with
character offsets into the raw text. The model only ever names a chunk and the first/last words of
the span it wants; the quote itself is sliced from the raw text here, so it is verbatim by
construction (the citation score only counts spans found word-for-word in the corpus).
"""
from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .schema import DATA

CORPUS_DIR = DATA / "corpus"
MANIFEST = CORPUS_DIR / "manifest.csv"


@dataclass
class Chunk:
    id: str
    start: int
    end: int
    text: str


@dataclass
class Document:
    doc_id: str
    title: str
    kind: str
    state: str
    county: str
    city: str
    citation: str
    url: str
    retrieval_date: str
    file: str
    status: str = "ok"
    text: str = ""
    chunks: list[Chunk] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    @property
    def level(self) -> str:
        if self.city:
            return "city"
        if self.county:
            return "county"
        return "state"


def read_manifest(path: Path = MANIFEST) -> list[dict]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [{k.strip(): (v or "").strip() for k, v in row.items()} for row in csv.DictReader(f)]


def load_document(row: dict, corpus_dir: Path = CORPUS_DIR) -> Optional[Document]:
    file = row.get("file") or ""
    if not file or row.get("status", "ok") not in ("ok", ""):
        return None
    p = corpus_dir / file
    if not p.exists():
        return None
    text = p.read_text(encoding="utf-8", errors="replace")
    doc = Document(doc_id=row["doc_id"], title=row.get("title", ""), kind=row.get("kind", "statute"),
                   state=row.get("state", "").upper(), county=row.get("county", ""), city=row.get("city", ""),
                   citation=row.get("citation", ""), url=row.get("url", ""), retrieval_date=row.get("retrieval_date", ""),
                   file=file, status=row.get("status", "ok") or "ok", text=text,
                   extra={k: v for k, v in row.items() if k not in ("doc_id", "title", "kind", "state", "county", "city", "citation", "url", "retrieval_date", "file", "status")})
    doc.chunks = chunk_text(text)
    return doc


def load_corpus(manifest: Path = MANIFEST, corpus_dir: Path = CORPUS_DIR) -> list[Document]:
    docs = []
    for row in read_manifest(manifest):
        d = load_document(row, corpus_dir)
        if d is not None:
            docs.append(d)
    return docs


# ----------------------------------------------------------------------------- chunking
_PARA = re.compile(r"\n[ \t]*\n+")
MAX_CHUNK = 1800


def chunk_text(text: str) -> list[Chunk]:
    """Paragraph chunks with raw offsets. Long paragraphs are split at sentence ends."""
    chunks: list[Chunk] = []
    pos = 0
    pieces: list[tuple[int, int]] = []
    for m in _PARA.finditer(text):
        if m.start() > pos:
            pieces.append((pos, m.start()))
        pos = m.end()
    if pos < len(text):
        pieces.append((pos, len(text)))
    for s, e in pieces:
        seg = text[s:e]
        if not seg.strip():
            continue
        if len(seg) <= MAX_CHUNK:
            pieces2 = [(s, e)]
        else:
            pieces2 = []
            cur = s
            while e - cur > MAX_CHUNK:
                window = text[cur : cur + MAX_CHUNK]
                cut = max(window.rfind(". "), window.rfind(".\n"), window.rfind("; "))
                if cut < MAX_CHUNK // 3:
                    cut = MAX_CHUNK
                else:
                    cut += 1
                pieces2.append((cur, cur + cut))
                cur += cut
            pieces2.append((cur, e))
        for s2, e2 in pieces2:
            # trim leading/trailing whitespace but keep offsets exact
            seg2 = text[s2:e2]
            lead = len(seg2) - len(seg2.lstrip())
            trail = len(seg2) - len(seg2.rstrip())
            s3, e3 = s2 + lead, e2 - trail
            if e3 > s3:
                chunks.append(Chunk(id=f"c{len(chunks) + 1}", start=s3, end=e3, text=text[s3:e3]))
    return chunks


def render_chunks(doc: Document, chunks: Optional[list[Chunk]] = None) -> str:
    return "\n\n".join(f"[{c.id}] {c.text}" for c in (chunks or doc.chunks))


# ----------------------------------------------------------------------------- quote slicing
def _fold(s: str) -> str:
    """Lossy normalisation used only for locating text: quotes, dashes, whitespace, case."""
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("‘", "'").replace("’", "'").replace("“", '"').replace("”", '"')
    s = s.replace("–", "-").replace("—", "-").replace(" ", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def _find_folded(hay: str, needle: str) -> Optional[tuple[int, int]]:
    """Find `needle` in `hay` ignoring whitespace runs and quote styles; return raw offsets in hay."""
    if not needle:
        return None
    # Build folded hay with a map back to raw indices.
    folded_chars: list[str] = []
    index_map: list[int] = []
    prev_space = True
    for i, ch in enumerate(hay):
        f = _fold(ch) if not ch.isspace() else " "
        if f == "":
            continue
        if f == " ":
            if prev_space:
                continue
            prev_space = True
            folded_chars.append(" ")
            index_map.append(i)
        else:
            prev_space = False
            for fc in f:
                folded_chars.append(fc)
                index_map.append(i)
    fh = "".join(folded_chars)
    fn = _fold(needle)
    k = fh.find(fn)
    if k == -1:
        return None
    start = index_map[k]
    end = index_map[k + len(fn) - 1] + 1
    return start, end


def slice_quote(doc: Document, chunk_id: str, start_words: str = "", end_words: str = "",
                max_len: int = 1200) -> tuple[str, list[int]]:
    """Return (verbatim quote, [start, end]) from the raw text of the document.

    The span runs from the first occurrence of `start_words` to the end of the first occurrence of
    `end_words` after it, inside the named chunk (falling back to the whole document, then to the
    whole chunk). The returned string is text[start:end] exactly.
    """
    chunk = next((c for c in doc.chunks if c.id == chunk_id), None)
    scopes = []
    if chunk is not None:
        scopes.append((chunk.start, chunk.end))
    scopes.append((0, len(doc.text)))
    for s0, e0 in scopes:
        hay = doc.text[s0:e0]
        a = _find_folded(hay, start_words) if start_words else None
        if start_words and a is None:
            continue
        start = s0 + a[0] if a else s0
        if end_words:
            b = _find_folded(doc.text[start:e0], end_words)
            if b is None:
                if chunk is not None and (s0, e0) == (chunk.start, chunk.end):
                    end = min(chunk.end, start + max_len)
                else:
                    continue
            else:
                end = start + b[1]
        else:
            end = min(e0, start + max_len)
        if end - start > max_len:
            end = start + max_len
            # back off to a word boundary
            cut = doc.text.rfind(" ", start, end)
            if cut > start + 40:
                end = cut
        if end > start:
            return doc.text[start:end], [start, end]
    if chunk is not None:
        end = min(chunk.end, chunk.start + max_len)
        return doc.text[chunk.start:end], [chunk.start, end]
    return "", [0, 0]


def quote_in_corpus(quote: str, docs: list[Document]) -> Optional[str]:
    """Return the doc_id that contains the quote verbatim, or None."""
    for d in docs:
        if quote and quote in d.text:
            return d.doc_id
    return None
