from bullwright_rag import chunk_report_body
from bullwright_rag.chunker import MAX_CHARS


def test_sections_become_chunks_with_metadata() -> None:
    body = {
        "summary": "A short but meaningful summary of the whole thesis in one paragraph.",
        "risks": [
            "Export controls could cap shipments to key regions materially.",
            "Custom silicon could erode share at the margin over time.",
        ],
    }
    chunks = chunk_report_body(body)
    assert [c.section for c in chunks] == ["summary", "risks", "risks"]
    assert [c.seq for c in chunks] == [0, 1, 2]


def test_long_sections_split_at_sentences() -> None:
    body = {"thesis": ("This sentence is a building block of a very long thesis. " * 80)}
    chunks = chunk_report_body(body)
    assert len(chunks) > 1
    assert all(len(c.text) <= MAX_CHARS for c in chunks)
    assert all(c.section == "thesis" for c in chunks)
    # nothing lost: total content preserved modulo whitespace
    total = sum(len(c.text) for c in chunks)
    assert total > len(body["thesis"]) * 0.95


def test_trivial_fragments_dropped() -> None:
    assert chunk_report_body({"urgency": "low"}) == []
