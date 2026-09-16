"""Decide how each bar is played, given the harmony and the form.

The layer between "what the chords are" and "what the parts do". Separating it
out is the point of the exercise: the renderer stays dumb and reliable, the
plan carries every choice, and **the plan is small enough to be produced by a
model and checked before it is used**.

What lives here now is a fixed policy — a stand-in that reads the form and
applies obvious rules. It exists to prove the mechanism and to give the model
something to beat, not because rules are the destination. A policy cannot know
that a phrase is a chorus, that a melody has gone quiet, or that a section has
been heard twice and wants lifting; those are judgements, and they are the
reason the plan is a separate object rather than a flag on the renderer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import music21

from musicxml_tools.chords import BarChord
from musicxml_tools.comping import BASS_TREATMENTS, DENSITIES
from musicxml_tools.form import Phrase, detect_form, phrase_for, summarise

DENSITY_NAMES = tuple(DENSITIES)

# A substitution must share this many pitch classes with the chord it replaces.
# Two is deliberately permissive: a tritone substitution shares only the third
# and seventh, and a relative minor only three tones, and both are the point of
# asking for substitutions at all. What it rejects is the failure C24 found —
# a harmonically unrelated chord that sounds fine in isolation and is in the
# wrong key.
MIN_SHARED_TONES = 2


@dataclass
class BarPlan:
    """How one bar is played."""

    bar: int
    density: str = "normal"
    """Comping density: sparse, normal or busy."""
    bass: str = "root-fifth"
    """Bass treatment: root-fifth, walk, pedal or anticipate."""


@dataclass
class ArrangementPlan:
    """Every per-bar decision, plus the form it was derived from."""

    bars: list[BarPlan] = field(default_factory=list)
    phrases: list[Phrase] = field(default_factory=list)
    substitutions: dict[int, str] = field(default_factory=dict)
    """Bar -> replacement chord symbol, already validated as related."""
    rejected: list[str] = field(default_factory=list)
    """Substitutions that failed validation, kept so they can be reported."""

    @property
    def density_by_bar(self) -> dict[int, str]:
        return {b.bar: b.density for b in self.bars}

    @property
    def bass_by_bar(self) -> dict[int, str]:
        return {b.bar: b.bass for b in self.bars}

    def apply_to(self, chords: list[BarChord]) -> list[BarChord]:
        """Return the chords with any accepted substitutions swapped in."""
        if not self.substitutions:
            return chords
        return [substitute(c, self.substitutions[c.bar]) or c
                if c.bar in self.substitutions else c for c in chords]

    def describe(self) -> str:
        densities = {b.density for b in self.bars}
        treatments = {b.bass for b in self.bars}
        parts = [
            f"{len(self.phrases)} phrases",
            f"densities {sorted(densities)}",
            f"bass {sorted(treatments)}",
        ]
        if self.substitutions:
            parts.append(f"{len(self.substitutions)} substitutions")
        if self.rejected:
            parts.append(f"{len(self.rejected)} rejected")
        return ", ".join(parts)


def chord_pitch_classes(figure: str) -> set[int] | None:
    """The pitch classes of a chord symbol, or None if it cannot be read."""
    try:
        symbol = music21.harmony.ChordSymbol(figure)
    except Exception:
        return None
    classes = {p.pitchClass for p in symbol.pitches}
    return classes or None


def is_related(chord: BarChord, figure: str) -> bool:
    """Is a proposed chord a substitution, or a different piece of music?"""
    proposed = chord_pitch_classes(figure)
    if proposed is None:
        return False
    existing = {music21.pitch.Pitch(t).pitchClass for t in chord.tones}
    return len(proposed & existing) >= MIN_SHARED_TONES


def substitute(chord: BarChord, figure: str) -> BarChord | None:
    """Swap a chord for a related one, or None if the swap is not legitimate."""
    if not is_related(chord, figure):
        return None
    classes = chord_pitch_classes(figure)
    if not classes:
        return None
    try:
        root = music21.harmony.ChordSymbol(figure).root().name
    except Exception:
        return None
    return BarChord(
        bar=chord.bar,
        root=root,
        tones=[music21.pitch.Pitch(pc).name for pc in sorted(classes)],
        figure=figure,
    )


# How a phrase is treated the first, second and later times it is heard. A
# repeat played identically is the thing that makes an arrangement sound like a
# loop; lifting it and then pulling back is the cheapest shape there is.
OCCURRENCE_DENSITY = ("normal", "busy", "sparse")


def plan_from_form(
    chords: list[BarChord], phrase_length: int = 4
) -> ArrangementPlan:
    """A fixed policy: vary on repeats, and lead into every chord change."""
    phrases = detect_form(chords, phrase_length)
    if not phrases:
        return ArrangementPlan()

    next_chord = {c.bar: n.figure for c, n in zip(chords, chords[1:])}
    bars: list[BarPlan] = []

    for chord in chords:
        phrase = phrase_for(phrases, chord.bar)
        if phrase is None:
            bars.append(BarPlan(bar=chord.bar))
            continue

        density = OCCURRENCE_DENSITY[min(phrase.occurrence, len(OCCURRENCE_DENSITY) - 1)]

        position = phrase.position(chord.bar)
        is_last = position == phrase.length - 1
        changes_next = next_chord.get(chord.bar) not in (None, chord.figure)

        if is_last and changes_next:
            # Arrive at the new chord rather than landing next to it.
            bass = "anticipate" if phrase.is_repeat else "walk"
        elif not changes_next and position == 0 and phrase.occurrence >= 2:
            # A section heard three times can afford to sit still.
            bass = "pedal"
        else:
            bass = "root-fifth"

        bars.append(BarPlan(bar=chord.bar, density=density, bass=bass))

    return ArrangementPlan(bars=bars, phrases=phrases)


def plan_schema() -> dict[str, Any]:
    """JSON Schema for a plan a model can return.

    Decisions are **per phrase**, not per bar: that is where they belong
    musically, and it keeps the response small — 28 phrases rather than 112
    bars on the longest score in the corpus. Substitutions are the exception,
    because reharmonising is a targeted act on one bar.
    """
    return {
        "type": "object",
        "required": ["phrases"],
        "additionalProperties": False,
        "properties": {
            "phrases": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["index", "density", "bass"],
                    "additionalProperties": False,
                    "properties": {
                        "index": {"type": "integer", "minimum": 0},
                        "density": {"enum": list(DENSITY_NAMES)},
                        "bass": {"enum": list(BASS_TREATMENTS)},
                    },
                },
            },
            "substitutions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["bar", "chord"],
                    "additionalProperties": False,
                    "properties": {
                        "bar": {"type": "integer", "minimum": 0},
                        "chord": {"type": "string"},
                    },
                },
            },
        },
    }


def describe_for_model(chords: list[BarChord], phrases: list[Phrase], key: str) -> str:
    """A compact description of the piece: what a plan is a response to."""
    by_bar = {c.bar: c.figure or c.root for c in chords}
    lines = [
        f"Key: {key}",
        f"Bars: {len(chords)}",
        f"Form: {summarise(phrases)}",
        "",
        "Phrases (index, label, bars, chords, times heard before):",
    ]
    for phrase in phrases:
        figures = " ".join(
            by_bar.get(b, "-") for b in range(phrase.start, phrase.start + phrase.length)
        )
        lines.append(
            f"  {phrase.index}  {phrase.label}  bars {phrase.start}-"
            f"{phrase.start + phrase.length - 1}  {figures}  (heard {phrase.occurrence}x)"
        )
    return "\n".join(lines)


def plan_from_model(
    chords: list[BarChord], phrases: list[Phrase], response: dict[str, Any]
) -> ArrangementPlan:
    """Build a plan from a model response, keeping only what validates.

    Anything unusable is dropped rather than rejected wholesale: a bad
    substitution costs that bar its reharmonisation, not the whole arrangement
    its plan. Rejections are recorded so they can be reported instead of
    silently absorbed (finding C3).
    """
    by_index = {p.index: p for p in phrases}
    choices = {
        entry["index"]: entry
        for entry in response.get("phrases", [])
        if entry.get("index") in by_index
    }

    next_figure = {c.bar: n.figure for c, n in zip(chords, chords[1:])}
    by_bar_chord = {c.bar: c for c in chords}

    substitutions: dict[int, str] = {}
    rejected: list[str] = []
    for entry in response.get("substitutions", []):
        bar, figure = entry.get("bar"), entry.get("chord", "")
        chord = by_bar_chord.get(bar)
        if chord is None:
            rejected.append(f"bar {bar}: no such bar")
        elif not is_related(chord, figure):
            rejected.append(f"bar {bar}: {figure!r} unrelated to {chord.figure}")
        else:
            substitutions[bar] = figure

    bars: list[BarPlan] = []
    for chord in chords:
        phrase = phrase_for(phrases, chord.bar)
        entry = choices.get(phrase.index, {}) if phrase else {}
        density = entry.get("density", "normal")
        bass = entry.get("bass", "root-fifth")

        # The model chooses the phrase's feel; leading into a chord change stays
        # a rule, because it depends on the next bar rather than on taste.
        if phrase and chord.bar == phrase.start + phrase.length - 1:
            if next_figure.get(chord.bar) not in (None, chord.figure):
                bass = "anticipate" if phrase.is_repeat else "walk"

        bars.append(BarPlan(bar=chord.bar, density=density, bass=bass))

    return ArrangementPlan(
        bars=bars, phrases=phrases, substitutions=substitutions, rejected=rejected
    )
