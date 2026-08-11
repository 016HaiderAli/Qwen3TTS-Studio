"""Unit tests for script chunking (notebook port + documented deviation)."""
import pytest

from app import chunking


def test_single_sentence():
    assert chunking.chunk_script("Hello world.") == ["Hello world."]


def test_simple_split_across_chunks():
    text = " ".join(f"word{i}." for i in range(100))
    chunks = chunking.chunk_script(text, max_words_per_chunk=80)
    assert len(chunks) == 2
    assert all(len(c.split()) <= 80 for c in chunks)


def test_paragraphs_are_kept():
    text = "First paragraph sentence one.\n\nSecond paragraph sentence two."
    chunks = chunking.chunk_script(text, max_words_per_chunk=80)
    assert len(chunks) == 1
    assert "\n\n" in chunks[0]


def test_paragraph_boundary_across_chunk_split():
    """A sentence on the other side of a paragraph break stays intact."""
    para1 = " ".join(f"word{i}." for i in range(75))
    para2 = " ".join(f"next{i}." for i in range(10))
    text = f"{para1}\n\n{para2}"
    chunks = chunking.chunk_script(text, max_words_per_chunk=80)
    assert len(chunks) == 2
    assert chunks[1].startswith("next")


def test_paragraph_break_preserved_in_first_chunk():
    para1 = " ".join(f"word{i}." for i in range(10))
    para2 = " ".join(f"next{i}." for i in range(5))
    text = f"{para1}\n\n{para2}"
    chunks = chunking.chunk_script(text, max_words_per_chunk=80)
    assert len(chunks) == 1
    assert "\n\n" in chunks[0]


def test_punctuation_not_required():
    text = "no punctuation here at all"
    assert chunking.chunk_script(text) == ["no punctuation here at all"]


def test_empty_script_raises():
    with pytest.raises(ValueError):
        chunking.chunk_script("   ")


def test_word_count():
    assert chunking.word_count("one two three") == 3


def test_split_sentences_returns_paragraph_membership():
    text = "One. Two.\n\nThree."
    pairs = chunking.split_sentences(text)
    assert [s for s, _ in pairs] == ["One.", "Two.", "Three."]
    assert [p for _, p in pairs] == [0, 0, 1]
