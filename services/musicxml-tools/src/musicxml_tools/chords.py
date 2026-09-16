"""Work out the harmony of a score: which chord, and for how long.

The first version scored 100% on every mechanical metric and still sounded
wrong, because it answered the question one bar at a time. It produced a chord
change in **every bar** — `D C D C D B♭ D B♭ …` — by reading each step of a
walking bass as a new harmony. Music holds a chord for two or four bars; that
oscillation is most of why the result read as restless rather than chill.

Two changes fix it, and they work together:

**A vocabulary.** Candidates are the diatonic sevenths of the detected key plus
the borrowings that actually occur, instead of "the four loudest pitch classes"
— which produced things like `CsusaddB-,omitG` and `Dpower/C`, chords nobody
plays and nobody can voice.

**A cost for changing.** Bars are decoded with Viterbi over the whole piece:
each candidate is scored on how well it explains the bar, and switching chord
carries a penalty. A bass that walks through a passing tone no longer drags the
harmony with it, because one bar of weak evidence cannot outweigh the cost of
moving and moving back.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass
from typing import Any

import music21

from musicxml_tools.chunking import PART_NAMES, bar_length, bar_of

# Intervals above the root, in semitones.
QUALITIES: dict[str, tuple[int, ...]] = {
    "maj7": (0, 4, 7, 11),
    "7": (0, 4, 7, 10),
    "m7": (0, 3, 7, 10),
    "m7b5": (0, 3, 6, 10),
    "dim7": (0, 3, 6, 9),
    "maj": (0, 4, 7),
    "min": (0, 3, 7),
}

# Scale degrees and the quality built on each, for the two modes we resolve to.
MAJOR_DEGREES = ((0, "maj7"), (2, "m7"), (4, "m7"), (5, "maj7"), (7, "7"), (9, "m7"), (11, "m7b5"))
MINOR_DEGREES = ((0, "m7"), (2, "m7b5"), (3, "maj7"), (5, "m7"), (7, "m7"), (8, "maj7"), (10, "7"))
# Borrowings common enough to earn a place: the dominant seventh on V (harmonic
# minor's defining chord) and the major subtonic.
MINOR_BORROWED = ((7, "7"), (10, "maj7"))

# Cost of changing chord between bars, in the same units as the emission score
# (a share of the bar's sounding weight). Roughly: a new chord must explain the
# bar this much better than holding the old one. Tuned so a two-bar vamp holds
# and a real four-bar progression still moves.
# Swept over the corpus against ROOT_BONUS rather than guessed. The two are
# in tension: the bonus pulls the harmony onto the bass note, the penalty holds
# it still. At 0.15 the harmony tracks the bass too closely (Vampire Killer
# oscillates at 1.2 bars per chord); at 0.80 it congeals (4.8) and root
# accuracy falls with it. 0.35 keeps root accuracy at its maximum — raising the
# penalty further buys nothing — while holding each chord for 2.7 bars, which
# is a change every two to four bars.
CHANGE_PENALTY = 0.35

# Weight of a sounding pitch class that is not in the chord, as a fraction of
# what an in-chord tone contributes. Non-chord tones are normal — passing
# notes, melody tensions — so the penalty is mild.
NON_CHORD_PENALTY = 0.45

# Bonus when the candidate's root is what the bass is actually playing.
# Without it, membership is all that counts and a C-major bar scores the same
# for Cmaj7 and Fmaj7 — both contain C and E — so the chord is chosen by
# whichever the change penalty happens to be holding. The bass note is the
# root far more often than it is the third or the fifth, and the harmony should
# say so.
ROOT_BONUS = 0.5


@dataclass(frozen=True)
class Candidate:
    """One chord the harmony could be sitting on."""

    root: int
    quality: str

    @property
    def pitch_classes(self) -> frozenset[int]:
        return frozenset((self.root + i) % 12 for i in QUALITIES[self.quality])

    @property
    def figure(self) -> str:
        name = music21.pitch.Pitch(self.root).name
        suffix = {"maj7": "maj7", "7": "7", "m7": "m7", "m7b5": "m7b5",
                  "dim7": "dim7", "maj": "", "min": "m"}[self.quality]
        return f"{name}{suffix}"


@dataclass
class BarChord:
    """The harmony sounding in one bar."""

    bar: int
    root: str
    tones: list[str]
    figure: str = ""


def detect_key(ir: dict[str, Any]) -> music21.key.Key:
    """The key, from metadata where the splitter recorded one."""
    for field in ("key", "key_signature"):
        name = ir.get("metadata", {}).get(field)
        if not name:
            continue
        try:
            return music21.key.Key(*name.split())
        except Exception:
            continue
    return music21.key.Key("C")


def candidates_for(key: music21.key.Key) -> list[Candidate]:
    """The chords a piece in this key is likely to use."""
    tonic = key.tonic.pitchClass
    degrees = MAJOR_DEGREES if key.mode == "major" else MINOR_DEGREES
    chords = [Candidate((tonic + step) % 12, quality) for step, quality in degrees]
    if key.mode != "major":
        chords += [Candidate((tonic + step) % 12, quality) for step, quality in MINOR_BORROWED]
    return chords


def _bass_roots(ir: dict[str, Any]) -> dict[int, int]:
    """The pitch class the bass holds longest in each bar."""
    metadata = ir.get("metadata", {})
    length = bar_length(metadata.get("time_signature", "4/4"))
    pickup = float(metadata.get("pickup", 0.0) or 0.0)

    per_bar: dict[int, Counter] = {}
    for event in ir["parts"].get("bass", []):
        if event.get("rest"):
            continue
        bar = bar_of(float(event["offset"]), length, pickup)
        names = event.get("pitches") or [event["pitch"]]
        for name in names:
            pc = music21.pitch.Pitch(name).pitchClass
            per_bar.setdefault(bar, Counter())[pc] += float(event["duration"])
    return {bar: c.most_common(1)[0][0] for bar, c in per_bar.items() if c}


def _weights_by_bar(ir: dict[str, Any]) -> dict[int, Counter]:
    metadata = ir.get("metadata", {})
    length = bar_length(metadata.get("time_signature", "4/4"))
    pickup = float(metadata.get("pickup", 0.0) or 0.0)

    bars: dict[int, Counter] = {}
    for part in PART_NAMES:
        # The bass is the strongest evidence for the root, so it counts double.
        weight = 2.0 if part == "bass" else 1.0
        for event in ir["parts"].get(part, []):
            if event.get("rest"):
                continue
            bar = bar_of(float(event["offset"]), length, pickup)
            names = event.get("pitches") or [event["pitch"]]
            for name in names:
                pc = music21.pitch.Pitch(name).pitchClass
                bars.setdefault(bar, Counter())[pc] += float(event["duration"]) * weight
    return bars


def _emission(weights: Counter, candidate: Candidate, bass_root: int | None) -> float:
    """How well a chord explains a bar, normalised to its total weight."""
    total = sum(weights.values())
    if not total:
        return 0.0
    tones = candidate.pitch_classes
    score = sum(w if pc in tones else -w * NON_CHORD_PENALTY for pc, w in weights.items())
    score /= total
    if bass_root is not None and candidate.root == bass_root:
        score += ROOT_BONUS
    return score


def detect_chords(ir: dict[str, Any]) -> list[BarChord]:
    """Decode one chord per bar, with a cost for changing.

    Viterbi rather than per-bar argmax: the best explanation of *the piece* is
    not the concatenation of the best explanations of each bar, because holding
    a chord through a bar of weak evidence is usually right.
    """
    weights = _weights_by_bar(ir)
    if not weights:
        return []

    bars = sorted(weights)
    bass_roots = _bass_roots(ir)
    key = detect_key(ir)
    options = candidates_for(key)
    if not options:
        return []

    # Viterbi forward pass.
    best: dict[Candidate, float] = {
        c: _emission(weights[bars[0]], c, bass_roots.get(bars[0])) for c in options
    }
    back: list[dict[Candidate, Candidate]] = []

    for bar in bars[1:]:
        scores: dict[Candidate, float] = {}
        pointers: dict[Candidate, Candidate] = {}
        for c in options:
            emission = _emission(weights[bar], c, bass_roots.get(bar))
            previous, value = max(
                ((p, best[p] - (0.0 if p == c else CHANGE_PENALTY)) for p in options),
                key=lambda pair: pair[1],
            )
            scores[c] = value + emission
            pointers[c] = previous
        best, _ = scores, back.append(pointers)

    # Backward pass.
    chain = [max(best, key=best.get)]
    for pointers in reversed(back):
        chain.append(pointers[chain[-1]])
    chain.reverse()

    return [
        BarChord(
            bar=bar,
            root=music21.pitch.Pitch(c.root).name,
            tones=[music21.pitch.Pitch((c.root + i) % 12).name for i in QUALITIES[c.quality]],
            figure=c.figure,
        )
        for bar, c in zip(bars, chain)
    ]
