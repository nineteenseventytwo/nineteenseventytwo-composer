"""Measure an arrangement against the score it came from.

Built after the first real inference run (finding C24), which produced a
stylistically convincing bossa bass in the wrong harmony: root–fifth movement,
long notes, textbook shape — and the original root kept in only 8 bars of 32.
A listener would call that "not the tune". Every metric here exists because it
catches something that run got wrong.

The metrics are deliberately mechanical, and deliberately not the whole story.
They answer "did it keep the piece" and "did it stay playable"; they cannot
answer "is it any good", which is why a listening pass stays in the loop
(finding C20).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import music21
from musicxml_tools.chunking import PART_NAMES, bar_length, bar_of, count_bars


def _pitches(event: dict[str, Any]) -> list[str]:
    if event.get("rest"):
        return []
    if "pitches" in event:
        return list(event["pitches"])
    return [event["pitch"]]


def _pitch_class(name: str) -> int:
    return music21.pitch.Pitch(name).pitchClass


def _by_bar(ir: dict[str, Any], part: str) -> dict[int, list[dict]]:
    metadata = ir.get("metadata", {})
    length = bar_length(metadata.get("time_signature", "4/4"))
    pickup = float(metadata.get("pickup", 0.0) or 0.0)

    bars: dict[int, list[dict]] = {}
    for event in ir["parts"].get(part, []):
        bars.setdefault(bar_of(float(event["offset"]), length, pickup), []).append(event)
    return bars


def _predominant(events: list[dict]) -> int | None:
    """The pitch class sounding for the longest in a bar.

    Weighted by duration rather than counted: a bossa bass plays the root long
    and the fifth short, so counting events would call the fifth the root
    whenever the bar has more of them.
    """
    weights: Counter[int] = Counter()
    for event in events:
        for name in _pitches(event):
            weights[_pitch_class(name)] += float(event["duration"])
    if not weights:
        return None
    return weights.most_common(1)[0][0]


@dataclass
class ArrangementMetrics:
    """What a mechanical check can say about an arrangement."""

    bars: int = 0
    root_exact: float = 0.0
    """Bars where the bass's predominant pitch class matches the source's."""
    root_present: float = 0.0
    """Bars where the source's root appears anywhere in the arranged bass."""
    root_grounded: float = 0.0
    """Bars where the arranged root is sounding *somewhere* in the source bar.

    The metric that survives holding a chord. ``root_exact`` compares bar by
    bar, so an arrangement that correctly sustains one harmony while the source
    bass walks beneath it scores as a miss — the metric and the music disagree.
    This asks the weaker but more honest question: is the root we played
    actually in the piece at that moment, or did we invent it? C24's failure
    scores near zero here; a held chord does not.
    """
    harmony_fidelity: float = 0.0
    """Share of arranged harmony pitch classes that were sounding in that bar."""
    coverage: dict[str, float] = field(default_factory=dict)
    """Share of source-occupied bars that still have content, per part."""
    event_ratio: dict[str, float] = field(default_factory=dict)
    """Arranged events over source events. Below 1.0 is thinning, which is wanted."""
    offsets_in_bar: float = 0.0
    """Share of events starting inside the bar they are assigned to."""
    bars_per_chord: float = 0.0
    """How long the harmony holds. The metric the first pass was missing.

    Its absence is why an arrangement could score 100% on everything else and
    still sound restless: the harmony changed in every bar, and nothing
    measured that. Two to four is idiomatic; near 1.0 is oscillation and a very
    high number is a drone.
    """

    def summary(self) -> str:
        return (
            f"root {self.root_exact:.0%} exact / {self.root_grounded:.0%} grounded · "
            f"harmony {self.harmony_fidelity:.0%} · "
            f"coverage {min(self.coverage.values(), default=0):.0%} min · "
            f"offsets {self.offsets_in_bar:.0%} · "
            f"{self.bars_per_chord:.1f} bars/chord"
        )


def evaluate(source: dict[str, Any], arranged: dict[str, Any]) -> ArrangementMetrics:
    """Compare an arrangement with its source, bar by bar."""
    metrics = ArrangementMetrics(bars=count_bars(source))

    src_bass, out_bass = _by_bar(source, "bass"), _by_bar(arranged, "bass")
    judged = [b for b, events in src_bass.items() if _predominant(events) is not None]

    if judged:
        exact = present = 0
        for bar in judged:
            root = _predominant(src_bass[bar])
            arranged_bar = out_bass.get(bar, [])
            if _predominant(arranged_bar) == root:
                exact += 1
            if root in {
                _pitch_class(name) for e in arranged_bar for name in _pitches(e)
            }:
                present += 1
        metrics.root_exact = exact / len(judged)
        metrics.root_present = present / len(judged)

    # Is the root we played present anywhere in that bar of the source?
    src_bar_pcs: dict[int, set[int]] = {}
    for part in PART_NAMES:
        for bar, events in _by_bar(source, part).items():
            src_bar_pcs.setdefault(bar, set()).update(
                _pitch_class(n) for e in events for n in _pitches(e)
            )
    grounded = checked = 0
    for bar, events in out_bass.items():
        root = _predominant(events)
        if root is None:
            continue
        checked += 1
        if root in src_bar_pcs.get(bar, set()):
            grounded += 1
    metrics.root_grounded = grounded / checked if checked else 0.0

    # Harmony fidelity: an arranged chord tone that was not sounding anywhere in
    # that bar of the source is an invention. Bossa voicings legitimately add
    # 9ths and 13ths, so this is expected to sit below 1.0 — it is a drift
    # detector, not a correctness test.
    kept = total = 0
    src_all: dict[int, set[int]] = {}
    for part in PART_NAMES:
        for bar, events in _by_bar(source, part).items():
            src_all.setdefault(bar, set()).update(
                _pitch_class(n) for e in events for n in _pitches(e)
            )
    for bar, events in _by_bar(arranged, "harmony").items():
        for event in events:
            for name in _pitches(event):
                total += 1
                if _pitch_class(name) in src_all.get(bar, set()):
                    kept += 1
    metrics.harmony_fidelity = kept / total if total else 0.0

    for part in PART_NAMES:
        src, out = _by_bar(source, part), _by_bar(arranged, part)
        occupied = [b for b, e in src.items() if e]
        metrics.coverage[part] = (
            sum(1 for b in occupied if out.get(b)) / len(occupied) if occupied else 1.0
        )
        src_n = len(source["parts"].get(part, []))
        metrics.event_ratio[part] = (
            len(arranged["parts"].get(part, [])) / src_n if src_n else 0.0
        )

    # Offsets must start inside their own bar. A model that drifts here produces
    # notes that land in the wrong measure after reassembly.
    length = bar_length(source.get("metadata", {}).get("time_signature", "4/4"))
    pickup = float(source.get("metadata", {}).get("pickup", 0.0) or 0.0)
    inside = seen = 0
    for part in PART_NAMES:
        for event in arranged["parts"].get(part, []):
            seen += 1
            offset = float(event["offset"])
            bar = bar_of(offset, length, pickup)
            start = pickup + (bar - 1) * length if (pickup and bar) else bar * length
            if 0 <= offset - start < length + 1e-9:
                inside += 1
    metrics.offsets_in_bar = inside / seen if seen else 1.0

    # Harmonic rhythm, read off the arranged harmony: consecutive bars sharing
    # a pitch-class set are one chord being held.
    voiced = _by_bar(arranged, "harmony")
    shapes = [
        frozenset(_pitch_class(n) for e in voiced[bar] for n in _pitches(e))
        for bar in sorted(voiced)
    ]
    if shapes:
        changes = sum(1 for a, b in zip(shapes, shapes[1:]) if a != b)
        metrics.bars_per_chord = len(shapes) / (changes + 1)

    return metrics
