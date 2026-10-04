from app.corpus import Document, chunk_text, slice_quote

TEXT = """# Test Ordinance | Ord. 1 | file://x | retrieved 2026-10-04

SECTION 1. Findings.
The Council finds that rents are high.

SECTION 2. Rent increase limit.
(a) No landlord shall increase the rent for a covered unit by more than five percent (5%) in any twelve-month period, “notwithstanding” any lease term to the contrary.
(b) This section applies to buildings with three or more dwelling units.

SECTION 3. Effective date. This ordinance shall take effect on January 1, 2027.
"""


def doc():
    d = Document(doc_id="doc_999", title="t", kind="ordinance", state="MA", county="Middlesex", city="Cambridge", citation="Ord. 1",
                 url="", retrieval_date="2026-10-04", file="x", text=TEXT)
    d.chunks = chunk_text(TEXT)
    return d


def test_chunks_have_exact_offsets():
    d = doc()
    assert len(d.chunks) >= 4
    for c in d.chunks:
        assert TEXT[c.start:c.end] == c.text


def test_slice_quote_is_verbatim_even_with_curly_quotes():
    d = doc()
    chunk = next(c for c in d.chunks if "five percent" in c.text)
    q, (s, e) = slice_quote(d, chunk.id, 'No landlord shall increase the rent', 'any twelve-month period, "notwithstanding" any lease term to the contrary.')
    assert q == TEXT[s:e]
    assert q.startswith("No landlord shall increase the rent") and q.endswith("to the contrary.")
    assert "“notwithstanding”" in q


def test_slice_quote_falls_back_to_chunk():
    d = doc()
    chunk = next(c for c in d.chunks if "five percent" in c.text)
    q, (s, e) = slice_quote(d, chunk.id, "words that are not there", "nor these")
    assert q == TEXT[s:e] and "five percent" in q
