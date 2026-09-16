"""Tests for the intermediate representation."""

import json

import music21

from musicxml_tools.intermediate import from_intermediate, to_intermediate, to_intermediate_json
from musicxml_tools.splitter import SplitParts


def _make_simple_parts() -> SplitParts:
    melody = music21.stream.Part()
    melody.partName = "Alto Sax"
    melody.insert(0, music21.note.Note("C5", quarterLength=1.0))
    melody.insert(1, music21.note.Note("D5", quarterLength=1.0))

    harmony = music21.stream.Part()
    harmony.partName = "Piano"
    harmony.insert(0, music21.chord.Chord(["E4", "G4"], quarterLength=2.0))

    bass = music21.stream.Part()
    bass.partName = "Bass"
    bass.insert(0, music21.note.Note("C3", quarterLength=2.0))

    return SplitParts(
        melody=melody,
        harmony=harmony,
        bass=bass,
        metadata={"title": "Test", "tempo": 120, "key": "C major", "time_signature": "4/4"},
    )


def test_to_intermediate_structure():
    parts = _make_simple_parts()
    ir = to_intermediate(parts)

    assert "metadata" in ir
    assert "parts" in ir
    assert "melody" in ir["parts"]
    assert "harmony" in ir["parts"]
    assert "bass" in ir["parts"]


def test_to_intermediate_melody():
    parts = _make_simple_parts()
    ir = to_intermediate(parts)

    melody = ir["parts"]["melody"]
    assert len(melody) == 2
    assert melody[0]["pitch"] == "C5"
    assert melody[1]["pitch"] == "D5"


def test_roundtrip():
    parts = _make_simple_parts()
    ir = to_intermediate(parts)
    restored = from_intermediate(ir)

    melody_notes = list(restored.melody.flatten().getElementsByClass(music21.note.Note))
    assert len(melody_notes) == 2
    assert melody_notes[0].nameWithOctave == "C5"


def test_json_serialization():
    parts = _make_simple_parts()
    json_str = to_intermediate_json(parts)
    data = json.loads(json_str)
    assert data["metadata"]["title"] == "Test"
