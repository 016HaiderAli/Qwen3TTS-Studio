"""Script chunking.

Port of the proven logic in reference/Voice_Studio.ipynb cells 46 and 55
(paragraph split -> sentence split -> greedy word-budget packing), with one
documented deviation (see docs/DEVIATIONS.md section 2): sentence boundaries
between different paragraphs are preserved inside a chunk with a blank line
instead of a single space, so Qwen3-TTS receives the original paragraph
structure and can interpret pauses and emphasis natively.
"""
import re

_PARAGRAPH_SPLIT = re.compile(r"\n\s*\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def _paragraphs(text: str) -> list[str]:
    return [
        p.strip() for p in _PARAGRAPH_SPLIT.split(text.strip()) if p.strip()
    ]


def _sentences(paragraph: str) -> list[str]:
    out = []
    for s in _SENTENCE_SPLIT.split(paragraph):
        s = s.strip()
        if s:
            out.append(s)
    return out


def split_sentences(text: str) -> list[tuple[str, int]]:
    """Return (sentence, paragraph_index) preserving paragraph membership."""
    result: list[tuple[str, int]] = []
    for pidx, paragraph in enumerate(_paragraphs(text)):
        for sentence in _sentences(paragraph):
            result.append((sentence, pidx))
    return result


def chunk_script(
    text: str,
    max_words_per_chunk: int = 80,
) -> list[str]:
    """Split a script into chunks of at most ``max_words_per_chunk`` words.

    Greedy sentence packing identical to the notebook; paragraph boundaries
    inside a chunk are preserved with a blank line.
    """
    text = (text or "").strip()
    if not text:
        raise ValueError("Script cannot be empty.")

    sentences = split_sentences(text)
    chunks: list[str] = []
    current: list[tuple[str, int]] = []
    current_words = 0

    for sentence, pidx in sentences:
        words = len(sentence.split())
        if current and current_words + words > max_words_per_chunk:
            chunks.append(_join(current))
            current = []
            current_words = 0
        current.append((sentence, pidx))
        current_words += words

    if current:
        chunks.append(_join(current))

    return chunks


def _join(sentences: list[tuple[str, int]]) -> str:
    parts: list[str] = []
    prev_paragraph: int | None = None
    for sentence, pidx in sentences:
        if prev_paragraph is not None and pidx != prev_paragraph:
            parts.append("\n\n")
        elif parts:
            parts.append(" ")
        parts.append(sentence)
        prev_paragraph = pidx
    return "".join(parts)


def word_count(text: str) -> int:
    return len(text.split())
