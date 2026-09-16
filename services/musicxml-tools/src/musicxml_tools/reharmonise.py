"""Generate the substitutions a bar could take, so nobody has to invent them.

Asked to propose substitutions in open prose, the model proposed none at all —
it read "sparingly" as "never". The fix is not firmer wording. It is to compute
the musically valid options here, where they can be constructed correctly, and
present them as a menu. The model then chooses, which is a question it can
answer and an answer that can be checked.

Same division as everywhere else in this package: the library knows what is
*possible*, the model decides what is *good*.

⚠️ Chord symbols use music21's ``-`` for flats, never ``b``. ``ChordSymbol``
**silently misparses** the ``b`` spelling — ``Db7`` returns D, F#, A, C, which
is a D7 — and rejects ``Bbmaj7`` outright. A wrong chord that parses is worse
than one that fails, so `normalise_figure` rewrites a leading ``b`` before
anything reads it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import pairwise

import music21

from musicxml_tools.chords import QUALITIES, BarChord

_FLAT_ROOT = re.compile(r"^([A-Ga-g])b")

SUFFIXES = {"maj7": "maj7", "7": "7", "m7": "m7", "m7b5": "m7b5",
            "dim7": "dim7", "maj": "", "min": "m"}


@dataclass(frozen=True)
class Candidate:
    """One substitution a bar could take, and why it works."""

    figure: str
    kind: str
    reason: str


def normalise_figure(figure: str) -> str:
    """Rewrite a leading ``b`` accidental to music21's ``-``.

    Only the root is touched: a ``b`` elsewhere is part of a quality such as
    ``m7b5``, which music21 reads correctly.
    """
    return _FLAT_ROOT.sub(lambda m: f"{m.group(1)}-", figure.strip())


def _figure(root_pc: int, quality: str) -> str:
    name = music21.pitch.Pitch(root_pc % 12).name  # music21 spells flats with "-"
    return f"{name}{SUFFIXES[quality]}"


def _quality_of(chord: BarChord) -> str:
    """Recover a chord's quality from its tones, defaulting to a minor seventh."""
    root = music21.pitch.Pitch(chord.root).pitchClass
    intervals = frozenset(
        (music21.pitch.Pitch(t).pitchClass - root) % 12 for t in chord.tones
    )
    for quality, shape in QUALITIES.items():
        if frozenset(i % 12 for i in shape) == intervals:
            return quality
    return "m7"


def candidates(chord: BarChord, following: BarChord | None) -> list[Candidate]:
    """Every substitution this bar could take, most idiomatic first.

    The four that carry bossa harmony. Two look *forward* — they are about
    arriving somewhere, so they only exist when another chord follows.
    """
    root = music21.pitch.Pitch(chord.root).pitchClass
    quality = _quality_of(chord)
    current = normalise_figure(chord.figure) if chord.figure else ""
    found: list[Candidate] = []

    def offer(figure: str, kind: str, reason: str) -> None:
        # A "substitution" identical to the chord it replaces is a no-op that
        # reads as a decision in the plan and changes nothing in the score.
        if normalise_figure(figure) != current:
            found.append(Candidate(figure, kind, reason))

    # Relative major/minor: the same notes heard from the other end.
    if quality in ("m7", "min"):
        offer(
            _figure(root + 3, "maj7"), "relative",
            "relative major — three tones in common, a lighter reading of the same bar",
        )
    elif quality in ("maj7", "maj"):
        offer(
            _figure(root - 3, "m7"), "relative",
            "relative minor — three tones in common, a darker reading of the same bar",
        )

    if following is not None:
        target = music21.pitch.Pitch(following.root).pitchClass
        # Is this bar already the dominant of what follows? If so it is doing
        # the work a turnaround would do, and most substitutions would undo it:
        # replacing V7 with the ii that precedes it trades a cadence for an
        # approach. Only the tritone substitution belongs here, because it
        # keeps the dominant function and changes the colour.
        already_dominant = quality == "7" and root == (target + 7) % 12

        if already_dominant:
            offer(
                _figure(target + 1, "7"), "tritone",
                f"♭II7 of {following.figure or following.root} — same pull, "
                "resolving down a semitone instead of up a fourth",
            )
        elif target != root:
            # V7 of what comes next: the commonest way to make a change sound
            # arrived at rather than merely adjacent.
            offer(
                _figure(target + 7, "7"), "secondary-dominant",
                f"V7 of {following.figure or following.root} — pulls into the next bar",
            )
            # Tritone sub of that dominant: the same pull, resolving down a
            # semitone. As close to a signature sound as bossa harmony has.
            offer(
                _figure(target + 1, "7"), "tritone",
                f"♭II7 of {following.figure or following.root} — semitone resolution",
            )
            # The ii that would precede it, for ii-V motion across the barline.
            offer(
                _figure(target + 2, "m7"), "ii-of-next",
                f"ii of {following.figure or following.root} — sets up a ii-V",
            )

    return found


def candidate_map(chords: list[BarChord]) -> dict[int, list[Candidate]]:
    """Substitutions available in each bar, keyed by bar."""
    following = {c.bar: n for c, n in pairwise(chords)}
    return {c.bar: candidates(c, following.get(c.bar)) for c in chords}
