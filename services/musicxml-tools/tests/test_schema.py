"""Tests for the intermediate-representation schema."""

import music21

from musicxml_tools import (
    EXAMPLE,
    intermediate_schema,
    split_voices,
    to_intermediate,
    validate_intermediate,
)


def _tiny_score() -> music21.stream.Score:
    score = music21.stream.Score()
    for pitches, clef in ((["C5", "E4"], music21.clef.TrebleClef()),
                          (["C3"], music21.clef.BassClef())):
        part = music21.stream.Part()
        measure = music21.stream.Measure(number=1)
        measure.insert(0, music21.meter.TimeSignature("4/4"))
        measure.insert(0, clef)
        measure.insert(0, music21.chord.Chord(pitches, quarterLength=4.0))
        part.append(measure)
        score.insert(0, part)
    return score


def test_example_conforms_to_schema():
    """The prompt's worked example must match what the parser accepts.

    Finding C2: the example taught {"bass": {"notes": [...]}} while the code
    produces {"bass": [...]}, so a model that obeyed it crashed the pipeline.
    This test is what stops that recurring.
    """
    assert validate_intermediate(EXAMPLE) == []


def test_real_intermediate_conforms_to_schema():
    ir = to_intermediate(split_voices(_tiny_score()))
    assert validate_intermediate(ir) == []


def test_rejects_wrongly_shaped_part():
    bad = {"metadata": {}, "parts": {"melody": {"notes": []}, "harmony": [], "bass": []}}
    errors = validate_intermediate(bad)
    assert errors and "melody" in errors[0]


def test_rejects_unknown_keys():
    bad = {"metadata": {}, "parts": {"melody": [], "harmony": [], "bass": []}, "extra": 1}
    assert validate_intermediate(bad)


def test_schema_covers_all_three_parts():
    parts = intermediate_schema()["properties"]["parts"]
    assert set(parts["required"]) == {"melody", "harmony", "bass"}
