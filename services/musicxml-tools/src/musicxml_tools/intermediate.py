"""Convert between music21 objects and compact intermediate representation for LLM processing."""

import json

import music21

from musicxml_tools.splitter import SplitParts


def to_intermediate(parts: SplitParts) -> dict:
    """Convert SplitParts to a compact JSON-serializable dict for LLM consumption.

    The intermediate representation is compact enough for LLM context windows
    while preserving musical information needed for bossa transformation.

    Args:
        parts: SplitParts from voice splitting.

    Returns:
        Dict with metadata and parts as note lists.
    """
    return {
        "metadata": parts.metadata,
        "parts": {
            "melody": _part_to_note_list(parts.melody),
            "harmony": _part_to_chord_list(parts.harmony),
            "bass": _part_to_note_list(parts.bass),
        },
    }


def to_intermediate_json(parts: SplitParts, indent: int = 2) -> str:
    """Convert SplitParts to a JSON string."""
    return json.dumps(to_intermediate(parts), indent=indent)


def from_intermediate(data: dict) -> SplitParts:
    """Convert intermediate representation back to SplitParts.

    Args:
        data: Dict with metadata and parts (as produced by to_intermediate).

    Returns:
        SplitParts with music21 Part objects.
    """
    metadata = data.get("metadata", {})
    parts_data = data.get("parts", {})
    time_signature = metadata.get("time_signature", "4/4")
    pickup = float(metadata.get("pickup", 0.0) or 0.0)

    melody = _note_list_to_part(parts_data.get("melody", []), "Alto Sax", time_signature, pickup)
    harmony = _chord_list_to_part(parts_data.get("harmony", []), "Piano", time_signature, pickup)
    bass = _note_list_to_part(parts_data.get("bass", []), "Bass", time_signature, pickup)

    return SplitParts(melody=melody, harmony=harmony, bass=bass, metadata=metadata)


def from_intermediate_json(json_str: str) -> SplitParts:
    """Convert a JSON string back to SplitParts."""
    return from_intermediate(json.loads(json_str))


def _part_to_note_list(part: music21.stream.Part) -> list[dict]:
    """Convert a monophonic part to a list of note dicts."""
    notes = []
    for elem in part.flatten().notesAndRests:
        if isinstance(elem, music21.note.Note):
            notes.append({
                "pitch": elem.nameWithOctave,
                "duration": float(elem.quarterLength),
                "offset": float(elem.offset),
            })
        elif isinstance(elem, music21.note.Rest):
            notes.append({
                "rest": True,
                "duration": float(elem.quarterLength),
                "offset": float(elem.offset),
            })
    return notes


def _part_to_chord_list(part: music21.stream.Part) -> list[dict]:
    """Convert a polyphonic part to a list of chord/note dicts."""
    items = []
    for elem in part.flatten().notesAndRests:
        if isinstance(elem, music21.chord.Chord):
            items.append({
                "pitches": [p.nameWithOctave for p in elem.pitches],
                "duration": float(elem.quarterLength),
                "offset": float(elem.offset),
            })
        elif isinstance(elem, music21.note.Note):
            items.append({
                "pitch": elem.nameWithOctave,
                "duration": float(elem.quarterLength),
                "offset": float(elem.offset),
            })
        elif isinstance(elem, music21.note.Rest):
            items.append({
                "rest": True,
                "duration": float(elem.quarterLength),
                "offset": float(elem.offset),
            })
    return items


def _note_list_to_part(
    notes: list[dict], name: str, time_signature: str = "4/4", pickup: float = 0.0
) -> music21.stream.Part:
    """Convert a note list back to a music21 Part."""
    part = music21.stream.Part()
    part.partName = name

    for item in notes:
        if item.get("rest"):
            elem = music21.note.Rest(quarterLength=item["duration"])
        else:
            elem = music21.note.Note(item["pitch"], quarterLength=item["duration"])
        part.insert(item["offset"], elem)

    return _barred(part, time_signature, pickup)


def _barred(
    part: music21.stream.Part, time_signature: str, pickup: float = 0.0
) -> music21.stream.Part:
    """Give a reconstructed part its time signature and bar it.

    The intermediate representation carries offsets but no metre, so a part
    rebuilt from it had neither a ``TimeSignature`` nor any ``Measure``
    objects. Two consequences, both visible in the output: music21's notation
    pass assumed 4/4 and mis-barred every score that was not in 4/4, and the
    pipeline's "count the measures" branch could never fire, always falling
    through to an estimate that disagreed with the drum part.
    """
    signature = music21.meter.TimeSignature(time_signature)
    bar_length = float(signature.barDuration.quarterLength)

    if pickup and 0 < pickup < bar_length:
        # Slide the music right so the pickup occupies the end of a full first
        # bar, bar it, then mark that bar as the anacrusis. Barring in place
        # would put the downbeat in the middle of measure one and every
        # subsequent barline in the wrong place.
        shifted = music21.stream.Part()
        shifted.partName = part.partName
        offset = bar_length - pickup
        for element in part.notesAndRests:
            shifted.insert(float(element.offset) + offset, element)
        part = shifted

    part.insert(0, signature)
    barred = part.makeMeasures()
    barred.partName = part.partName

    if pickup and 0 < pickup < bar_length:
        measures = list(barred.getElementsByClass(music21.stream.Measure))
        if measures:
            measures[0].padAsAnacrusis(useInitialRests=True)

    return barred


def _chord_list_to_part(
    items: list[dict], name: str, time_signature: str = "4/4", pickup: float = 0.0
) -> music21.stream.Part:
    """Convert a chord list back to a music21 Part."""
    part = music21.stream.Part()
    part.partName = name

    for item in items:
        if item.get("rest"):
            elem = music21.note.Rest(quarterLength=item["duration"])
        elif "pitches" in item:
            elem = music21.chord.Chord(item["pitches"], quarterLength=item["duration"])
        else:
            elem = music21.note.Note(item["pitch"], quarterLength=item["duration"])
        part.insert(item["offset"], elem)

    return _barred(part, time_signature, pickup)
