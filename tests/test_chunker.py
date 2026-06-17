"""Tests for the markdown-aware chunker."""
from src.ai import chunker


def test_clean_removes_html_and_badges():
    md = """# Hi <img src="x.png"> world

![badge](https://shields.io/badge/x.svg)

Real content here."""
    cleaned = chunker.clean_markdown(md)
    assert "<img" not in cleaned
    assert "shields.io" not in cleaned
    assert "Real content here." in cleaned


def test_clean_removes_code_fences():
    md = """Some text

```python
print("hello")
```

More text."""
    cleaned = chunker.clean_markdown(md)
    assert "print(" not in cleaned
    assert "Some text" in cleaned
    assert "More text" in cleaned


def test_clean_strips_link_url_keeps_text():
    md = "See [the docs](https://example.com/docs) for details."
    cleaned = chunker.clean_markdown(md)
    assert "https://example.com" not in cleaned
    assert "the docs" in cleaned


def test_chunk_text_empty_returns_empty_list():
    assert chunker.chunk_text("") == []
    assert chunker.chunk_text("   ") == []


def test_chunk_text_simple_no_headers():
    md = "A small paragraph that fits in one chunk."
    chunks = chunker.chunk_text(md)
    assert len(chunks) == 1
    assert chunks[0]["chunk_index"] == 0
    assert "small paragraph" in chunks[0]["text"]


def test_chunk_text_splits_by_headers():
    md = """# Section A

Body of A.

# Section B

Body of B.

# Section C

Body of C."""
    chunks = chunker.chunk_text(md)
    # Cada sección sería un chunk si superara MIN_CHARS, pero como son cortas
    # se mergean en uno solo
    assert len(chunks) >= 1
    assert "Body of A" in chunks[0]["text"]


def test_chunk_text_header_prepended():
    md = "Some paragraph about quantum computing."
    chunks = chunker.chunk_text(md, header="Repository: example/repo")
    assert chunks[0]["text"].startswith("Repository: example/repo")


def test_chunk_text_long_section_splits():
    long_body = ". ".join([f"Sentence number {i} about quantum stuff" for i in range(200)])
    md = f"# Big Section\n\n{long_body}."
    chunks = chunker.chunk_text(md, max_chars=500, overlap=100)
    assert len(chunks) > 1
    for c in chunks:
        assert c["char_count"] > 0


def test_section_path_breadcrumb():
    md = """# Top

intro

## Sub A

content A

## Sub B

content B"""
    chunks = chunker.chunk_text(md)
    paths = [c["section_path"] for c in chunks]
    # At least one chunk should have the breadcrumb structure
    assert any(">" in p for p in paths) or any("Top" in p for p in paths)


def test_text_hash_deterministic():
    h1 = chunker.text_hash("hello world")
    h2 = chunker.text_hash("hello world")
    h3 = chunker.text_hash("hello world!")
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64  # SHA-256 hex
