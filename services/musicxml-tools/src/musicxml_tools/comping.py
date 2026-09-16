"""Render the comping and bass parts from detected harmony.

Separated from chord detection because they answer different questions: what
the harmony *is*, and how it is *played*. The rhythm here is the anchor the
style rests on — block chords on every downbeat is what made the first pass
sound mechanical regardless of how good the chords were.

⚠️ **The partido alto grid below wants a musician's ear on it.** The mechanism
is data-driven so the pattern is one editable string, but the specific cell is
my best reading rather than something I can verify by listening. Correct it in
place; nothing else depends on its exact shape.
"""

from __future__ import annotations

from typing import Any

import music21

from musicxml_tools.chords import QUALITIES, BarChord
from musicxml_tools.chunking import bar_length

# Sixteenth-note grid, two bars, "x" = attack. Partido alto is a samba cell:
# denser than the bossa clave (sixteenths rather than eighths), heavily
# syncopated, and asymmetric across its two bars — the second bar answers the
# first rather than repeating it.
PARTIDO_ALTO = (
    "x..x..x...x..x..",
    "..x...x..x..x..x",
)

# Bossa's own comping figure, kept as the sparser alternative: the same
# syncopation as the bass, which is what makes the two lock together.
BOSSA_COMP = (
    "x.....x.x.....x.",
    "x.....x.x.....x.",
)

# Density variants of the partido alto cell. Not different patterns — the same
# cell with attacks removed or added, so the groove survives the variation.
# A renderer that can only do one thing makes form detection pointless: a plan
# that says "thinner on the repeat" needs something to call.
PARTIDO_ALTO_SPARSE = (
    "x.....x.........",
    "..x......x......",
)
PARTIDO_ALTO_BUSY = (
    "x..x..x.x.x..x.x",
    "..x.x.x..x..x..x",
)

PATTERNS = {"partido-alto": PARTIDO_ALTO, "bossa": BOSSA_COMP}
DENSITIES = {
    "sparse": PARTIDO_ALTO_SPARSE,
    "normal": PARTIDO_ALTO,
    "busy": PARTIDO_ALTO_BUSY,
}
DEFAULT_PATTERN = "partido-alto"
DEFAULT_DENSITY = "normal"

BASS_TREATMENTS = ("root-fifth", "walk", "pedal", "anticipate")

SIXTEENTH = 0.25

# Comping register. Rootless voicings sit here; the bass has the root.
COMP_LOW, COMP_HIGH = 55, 76  # G3..E5

BASS_OCTAVE = 2
BASS_FIGURE = ((0.0, "root", 1.5), (1.5, "fifth", 0.5), (2.0, "root", 1.5), (3.5, "fifth", 0.5))


def _bar_start(bar: int, length: float, pickup: float) -> float:
    if bar <= 0:
        return 0.0
    return pickup + (bar - 1) * length if pickup else bar * length


def rootless_voicing(chord: BarChord) -> list[str]:
    """Third, fifth, seventh and ninth, voiced close in the comping register.

    Rootless because the bass has the root — two instruments doubling it is the
    sound of an arrangement nobody voiced. The ninth is added because it is
    what makes a seventh chord sound Brazilian rather than merely correct.

    The whole voicing is placed as a unit and shifted by octaves to fit. Built
    note-by-note against a ceiling instead, a chord whose lowest tone happened
    to sit high lost its upper notes and came out as a bare dyad while its
    neighbour had four.
    """
    root = music21.pitch.Pitch(chord.root).pitchClass
    intervals = sorted(
        {(music21.pitch.Pitch(t).pitchClass - root) % 12 for t in chord.tones[1:]}
    )
    if not intervals:
        return []
    intervals = intervals + [14]  # the ninth, above whatever the chord has

    # Stack ascending in close position from an arbitrary low octave, then move
    # the finished shape into range.
    base = 36 + root
    midis: list[int] = []
    for interval in intervals:
        midi = base + interval
        while midis and midi <= midis[-1]:
            midi += 12
        midis.append(midi)

    while midis[0] < COMP_LOW:
        midis = [m + 12 for m in midis]
    while midis[-1] > COMP_HIGH and midis[0] - 12 >= COMP_LOW:
        midis = [m - 12 for m in midis]

    # Still too tall to fit: drop the ninth rather than return a fragment.
    if midis[-1] > COMP_HIGH and len(midis) > 2:
        midis = midis[:-1]

    return [music21.pitch.Pitch(m).nameWithOctave for m in midis if m <= COMP_HIGH]


def render_comp(
    chords: list[BarChord],
    ir: dict[str, Any],
    pattern: str = DEFAULT_PATTERN,
    density_by_bar: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Voicings placed on a rhythmic grid rather than on every downbeat.

    `density_by_bar` lets the caller thin or thicken individual bars — the
    mechanism form-aware arranging needs, and the hook the plan arranger will
    drive.
    """
    metadata = ir.get("metadata", {})
    length = bar_length(metadata.get("time_signature", "4/4"))
    pickup = float(metadata.get("pickup", 0.0) or 0.0)
    default_grid = PATTERNS.get(pattern, PARTIDO_ALTO)
    densities = density_by_bar or {}

    events: list[dict[str, Any]] = []
    for chord in chords:
        voicing = rootless_voicing(chord)
        if not voicing:
            continue
        start = _bar_start(chord.bar, length, pickup)
        grid = DENSITIES.get(densities.get(chord.bar, ""), default_grid)
        cell = grid[chord.bar % len(grid)]

        hits = [i for i, mark in enumerate(cell) if mark == "x" and i * SIXTEENTH < length]
        for index, position in enumerate(hits):
            offset = position * SIXTEENTH
            # Ring until the next attack, so the voicing sustains rather than
            # stabbing — the chord is holding the bar, not punctuating it.
            following = hits[index + 1] * SIXTEENTH if index + 1 < len(hits) else length
            events.append(
                {
                    "pitches": voicing,
                    "duration": round(min(following - offset, length - offset), 6),
                    "offset": start + offset,
                }
            )
    return events


def _approach(target: music21.pitch.Pitch, from_below: bool) -> music21.pitch.Pitch:
    """A leading note a semitone away — how a bass line arrives somewhere."""
    return target.transpose(-1 if from_below else 1)


def render_bass(
    chords: list[BarChord],
    ir: dict[str, Any],
    treatment_by_bar: dict[int, str] | None = None,
) -> list[dict[str, Any]]:
    """Bass line, with per-bar treatment.

    ``root-fifth``
        The bossa default: root long, fifth short and syncopated.
    ``walk``
        Replaces the last note with a semitone approach to the next bar's root.
        This is what makes a chord change sound arrived-at rather than merely
        adjacent, and it is why the last bar of a phrase should not look like
        the three before it.
    ``pedal``
        Holds the root. Space, for where the arrangement needs to sit still.
    ``anticipate``
        Brings the next root in early, on the and-of-four — the syncopation
        that pulls a new section forward instead of letting it start flat.
    """
    metadata = ir.get("metadata", {})
    length = bar_length(metadata.get("time_signature", "4/4"))
    pickup = float(metadata.get("pickup", 0.0) or 0.0)
    treatments = treatment_by_bar or {}
    next_root = {c.bar: n.root for c, n in zip(chords, chords[1:])}

    events: list[dict[str, Any]] = []
    for chord in chords:
        start = _bar_start(chord.bar, length, pickup)
        root = music21.pitch.Pitch(f"{chord.root}{BASS_OCTAVE}")
        fifth = root.transpose(7)
        treatment = treatments.get(chord.bar, "root-fifth")
        following = next_root.get(chord.bar)

        if treatment == "pedal":
            events.append({"pitch": root.nameWithOctave, "duration": length, "offset": start})
            continue

        figure = [(o, r, d) for o, r, d in BASS_FIGURE if o < length]
        for index, (offset, role, duration) in enumerate(figure):
            pitch = root if role == "root" else fifth
            is_last = index == len(figure) - 1

            if is_last and following and treatment in ("walk", "anticipate"):
                target = music21.pitch.Pitch(f"{following}{BASS_OCTAVE}")
                if treatment == "walk":
                    pitch = _approach(target, from_below=target.midi >= root.midi)
                else:
                    pitch = target

            events.append(
                {
                    "pitch": pitch.nameWithOctave,
                    "duration": min(duration, length - offset),
                    "offset": start + offset,
                }
            )
    return events
