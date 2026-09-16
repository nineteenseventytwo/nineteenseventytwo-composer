"""Tests for the arrangement pipeline."""

from pathlib import Path
from unittest.mock import AsyncMock, patch

import music21
import pytest

from composer.llm_client import TransformResult
from composer.pipeline import arrange


def _create_test_musicxml(path: Path) -> None:
    """Create a minimal piano MusicXML for testing."""
    score = music21.stream.Score()
    md = music21.metadata.Metadata()
    md.title = "Test"
    score.metadata = md

    treble = music21.stream.Part()
    m = music21.stream.Measure(number=1)
    m.insert(0, music21.meter.TimeSignature("4/4"))
    m.insert(0, music21.chord.Chord(["C5", "E4"], quarterLength=4.0))
    treble.append(m)

    bass_part = music21.stream.Part()
    mb = music21.stream.Measure(number=1)
    mb.insert(0, music21.meter.TimeSignature("4/4"))
    mb.insert(0, music21.note.Note("C3", quarterLength=4.0))
    bass_part.append(mb)

    score.insert(0, treble)
    score.insert(0, bass_part)
    score.write("musicxml", fp=str(path))


@pytest.mark.asyncio
async def test_arrange_produces_output(tmp_path):
    """The default arranger needs no model, so this exercises the real path."""
    input_path = tmp_path / "input.musicxml"
    output_path = tmp_path / "output.musicxml"
    _create_test_musicxml(input_path)

    result = await arrange(input_path, output_path)

    assert output_path.exists()
    score = music21.converter.parse(str(output_path))
    assert score is not None
    # melody, harmony, bass, drum kit, shaker — one staff per Game Boy channel
    # plus the live sax (docs/performance-context.md)
    assert len(score.parts) == 5
    assert result.transformed == result.total


@pytest.mark.asyncio
async def test_notes_arranger_is_still_reachable(tmp_path):
    input_path = tmp_path / "input.musicxml"
    output_path = tmp_path / "output.musicxml"
    _create_test_musicxml(input_path)

    with patch("composer.pipeline.get_arranger") as factory:
        factory.return_value.name = "notes"
        factory.return_value.transform_to_bossa = AsyncMock(
            side_effect=lambda ir: TransformResult(ir=ir)
        )
        await arrange(input_path, output_path)

    assert output_path.exists()
