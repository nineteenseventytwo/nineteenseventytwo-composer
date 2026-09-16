"""Find the shape of a piece: phrases, sections, and which of them repeat.

Without this the renderer treats bar 97 exactly like bar 1, because it has no
way to know they are the same music. Dr Wily came out as 112 bars carrying two
comping rhythms and a single bass figure — a loop rather than an arrangement,
and no improvement to the chords could have fixed it.

Form is what "vary the repeat", "thin out here" and "lift into the last eight"
are expressed in terms of. It is deliberately derived from the **harmony**
rather than the melody: the chord sequence is what defines a section, and it is
already the most reliable thing we compute.
"""

from __future__ import annotations

from dataclasses import dataclass

from musicxml_tools.chords import BarChord

DEFAULT_PHRASE = 4
"""Bars per phrase. Four is the near-universal unit in this repertoire."""


@dataclass
class Phrase:
    """One unit of form."""

    index: int
    start: int
    """First bar."""
    length: int
    label: str
    """Phrases with the same chord sequence share a label: A, B, C…"""
    occurrence: int
    """0 the first time this label appears, 1 the second, and so on.

    What makes "vary the repeat" possible: the renderer can treat a phrase
    differently *because* it has been heard before.
    """

    @property
    def is_repeat(self) -> bool:
        return self.occurrence > 0

    def position(self, bar: int) -> int:
        """Where a bar sits inside the phrase, 0-based."""
        return bar - self.start


def _label(index: int) -> str:
    letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    if index < len(letters):
        return letters[index]
    return f"{letters[index % len(letters)]}{index // len(letters) + 1}"


def detect_form(chords: list[BarChord], phrase: int = DEFAULT_PHRASE) -> list[Phrase]:
    """Group bars into phrases and label the ones that share a chord sequence."""
    if not chords or phrase < 1:
        return []

    by_bar = {c.bar: c.figure for c in chords}
    last = max(by_bar)

    signatures: dict[tuple[str, ...], str] = {}
    counts: dict[str, int] = {}
    phrases: list[Phrase] = []

    for index, start in enumerate(range(0, last + 1, phrase)):
        length = min(phrase, last + 1 - start)
        signature = tuple(by_bar.get(b, "") for b in range(start, start + length))

        label = signatures.get(signature)
        if label is None:
            label = _label(len(signatures))
            signatures[signature] = label

        phrases.append(
            Phrase(
                index=index,
                start=start,
                length=length,
                label=label,
                occurrence=counts.get(label, 0),
            )
        )
        counts[label] = counts.get(label, 0) + 1

    return phrases


def phrase_for(phrases: list[Phrase], bar: int) -> Phrase | None:
    """The phrase a bar belongs to."""
    for candidate in phrases:
        if candidate.start <= bar < candidate.start + candidate.length:
            return candidate
    return None


def summarise(phrases: list[Phrase]) -> str:
    """A compact form string such as "A A B A" — for logs and for prompts."""
    return " ".join(p.label for p in phrases)
