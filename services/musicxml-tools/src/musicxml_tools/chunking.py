"""Split an intermediate representation into bar-aligned chunks, and put it back.

Whole-score transformation is not merely wasteful, it is arithmetically
impossible: every score in the reference corpus serialises to more tokens than
the model can emit (finding C5). Chunking is therefore a prerequisite rather
than an optimisation.

Chunks are **bar-aligned and carry all three parts**. Splitting per part as well
would make each request smaller, but the harmony and bass decisions depend on
what the melody is doing in those bars — and voicing choices are most of the
musical judgement being asked for. Section-only chunking keeps that context
together.

Offsets are rebased to zero within each chunk: the numbers stay small, which
costs fewer tokens, and each chunk is independently valid against the schema so
it can be validated and retried on its own. Rebasing subtracts and re-adds the
same value and does **not** round — rounding to six places turned a triplet
offset of 3.6666666666666665 into 3.666667, and durations carry tuplet
information that music21 reads exactly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import music21

PART_NAMES = ("melody", "harmony", "bass")


@dataclass
class Chunk:
    """One bar-aligned slice of an arrangement, valid IR in its own right."""

    ir: dict[str, Any]
    start: float
    """Absolute offset in quarter notes that this chunk's zero corresponds to."""
    first_bar: int
    bars: int
    events: int = field(default=0)

    def __post_init__(self) -> None:
        if not self.events:
            self.events = sum(len(self.ir["parts"][name]) for name in PART_NAMES)


def bar_length(time_signature: str) -> float:
    """Length of one bar in quarter notes.

    Measured rather than taken from the numerator: 6/8 has six beats but a bar
    three quarter notes long.
    """
    return float(music21.meter.TimeSignature(time_signature).barDuration.quarterLength)


def bar_start(index: int, length: float, pickup: float) -> float:
    """Absolute offset where a bar begins, accounting for a pickup bar."""
    if index <= 0:
        return 0.0
    return pickup + (index - 1) * length if pickup else index * length


def bar_of(offset: float, length: float, pickup: float) -> int:
    """Which bar an offset falls in. Bar 0 is the pickup where one exists."""
    if pickup and offset < pickup:
        return 0
    if pickup:
        return 1 + int((offset - pickup) // length)
    return int(offset // length)


def count_bars(ir: dict[str, Any]) -> int:
    """How many bars the arrangement spans."""
    metadata = ir.get("metadata", {})
    length = bar_length(metadata.get("time_signature", "4/4"))
    pickup = float(metadata.get("pickup", 0.0) or 0.0)

    end = 0.0
    for name in PART_NAMES:
        for event in ir["parts"].get(name, []):
            end = max(end, float(event["offset"]) + float(event["duration"]))

    if end <= 0:
        return 0
    if pickup:
        return 1 + max(1, math.ceil((end - pickup) / length))
    return max(1, math.ceil(end / length))


def split_by_bars(ir: dict[str, Any], bars_per_chunk: int = 8) -> list[Chunk]:
    """Split an arrangement into chunks of whole bars.

    An event is assigned to the chunk containing its **onset**, so a note that
    sustains across a boundary stays intact rather than being cut in two.
    """
    if bars_per_chunk < 1:
        raise ValueError("bars_per_chunk must be at least 1")

    metadata = ir.get("metadata", {})
    length = bar_length(metadata.get("time_signature", "4/4"))
    pickup = float(metadata.get("pickup", 0.0) or 0.0)
    total = count_bars(ir)
    if total == 0:
        return []

    buckets: dict[int, dict[str, list]] = {}
    for name in PART_NAMES:
        for event in ir["parts"].get(name, []):
            bar = bar_of(float(event["offset"]), length, pickup)
            index = bar // bars_per_chunk
            buckets.setdefault(index, {n: [] for n in PART_NAMES})[name].append(event)

    chunks: list[Chunk] = []
    for index in sorted(buckets):
        first_bar = index * bars_per_chunk
        start = bar_start(first_bar, length, pickup)
        parts = {
            name: [
                {**event, "offset": float(event["offset"]) - start}
                for event in sorted(buckets[index][name], key=lambda e: e["offset"])
            ]
            for name in PART_NAMES
        }
        chunks.append(
            Chunk(
                ir={"metadata": dict(metadata), "parts": parts},
                start=start,
                first_bar=first_bar,
                bars=min(bars_per_chunk, total - first_bar),
            )
        )
    return chunks


def merge_chunks(chunks: list[Chunk], metadata: dict[str, Any]) -> dict[str, Any]:
    """Reassemble chunks into one arrangement, restoring absolute offsets."""
    parts: dict[str, list] = {name: [] for name in PART_NAMES}

    for chunk in sorted(chunks, key=lambda c: c.start):
        for name in PART_NAMES:
            for event in chunk.ir["parts"].get(name, []):
                parts[name].append(
                    {**event, "offset": float(event["offset"]) + chunk.start}
                )

    for name in PART_NAMES:
        parts[name].sort(key=lambda e: e["offset"])

    return {"metadata": dict(metadata), "parts": parts}
