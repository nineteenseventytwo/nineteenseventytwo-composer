"""Tests for the plan arranger — the model chooses, the library renders."""

from unittest.mock import AsyncMock, patch

import pytest
from musicxml_tools import validate_intermediate
from musicxml_tools.chords import detect_chords

from composer.arrangers import PlanArranger


def _ir(bars: int = 16) -> dict:
    """Four bars of Dm7 then four of B♭maj7, twice — an A B A B form."""
    cycle = [("D", "F", "A"), ("D", "F", "A"), ("D", "F", "A"), ("D", "F", "A"),
             ("B-", "D", "F"), ("B-", "D", "F"), ("B-", "D", "F"), ("B-", "D", "F")]
    melody, harmony, bass = [], [], []
    for b in range(bars):
        root, third, fifth = cycle[b % len(cycle)]
        offset = float(b * 4)
        melody.append({"pitch": f"{third}5", "duration": 4.0, "offset": offset})
        harmony.append({"pitches": [f"{third}4", f"{fifth}4"], "duration": 4.0, "offset": offset})
        bass.append({"pitch": f"{root}2", "duration": 4.0, "offset": offset})
    return {
        "metadata": {"time_signature": "4/4", "pickup": 0.0, "key": "d minor"},
        "parts": {"melody": melody, "harmony": harmony, "bass": bass},
    }


def _plan(**overrides) -> dict:
    base = {
        "phrases": [
            {"index": 0, "density": "normal", "bass": "root-fifth"},
            {"index": 1, "density": "sparse", "bass": "pedal"},
            {"index": 2, "density": "busy", "bass": "walk"},
            {"index": 3, "density": "sparse", "bass": "root-fifth"},
        ]
    }
    base.update(overrides)
    return base


@pytest.mark.asyncio
async def test_the_model_s_plan_reaches_the_rendering():
    arranger = PlanArranger()
    with patch.object(arranger.client, "ask_json", AsyncMock(return_value=_plan())):
        result = await arranger.transform_to_bossa(_ir())

    assert validate_intermediate(result.ir) == []
    assert result.transformed == result.total == 1
    # A sparse phrase and a busy one must not produce the same bar.
    def bar_events(part, bar):
        return [e for e in result.ir["parts"][part]
                if bar * 4 <= float(e["offset"]) < (bar + 1) * 4]
    assert len(bar_events("harmony", 4)) != len(bar_events("harmony", 8))


@pytest.mark.asyncio
async def test_an_unrelated_substitution_is_rejected_not_rendered():
    """C24's failure, arriving by a different route.

    A substitution the model invents must not reach the score unless it shares
    notes with the chord it replaces.
    """
    arranger = PlanArranger()
    response = _plan(substitutions=[{"bar": 3, "chord": "F#maj7"}])
    ir = _ir()
    with patch.object(arranger.client, "ask_json", AsyncMock(return_value=response)):
        result = await arranger.transform_to_bossa(ir)

    roots = {e["pitch"][:-1] for e in result.ir["parts"]["bass"]
             if 12.0 <= float(e["offset"]) < 16.0}
    assert "F#" not in roots


@pytest.mark.asyncio
async def test_a_related_substitution_is_accepted():
    arranger = PlanArranger()
    ir = _ir()
    detected = {c.bar: c.figure for c in detect_chords(ir)}
    assert detected[3] == "Dm7"

    response = _plan(substitutions=[{"bar": 3, "chord": "Fmaj7"}])  # relative major
    with patch.object(arranger.client, "ask_json", AsyncMock(return_value=response)):
        result = await arranger.transform_to_bossa(ir)

    roots = {e["pitch"][:-1] for e in result.ir["parts"]["bass"]
             if 12.0 <= float(e["offset"]) < 16.0}
    assert "F" in roots


@pytest.mark.asyncio
async def test_a_model_failure_falls_back_to_a_complete_arrangement():
    """A model outage should cost shape, not the piece.

    The deterministic path is harmonically sound on its own, so falling back to
    it leaves a usable score rather than nothing.
    """
    arranger = PlanArranger()
    with patch.object(arranger.client, "ask_json", AsyncMock(side_effect=RuntimeError("down"))):
        result = await arranger.transform_to_bossa(_ir())

    assert validate_intermediate(result.ir) == []
    assert result.ir["parts"]["bass"], "fallback must still produce a bass part"
    assert result.transformed == 0
    assert "down" in result.outcomes[0].reason


@pytest.mark.asyncio
async def test_phrases_the_model_ignored_still_get_played():
    arranger = PlanArranger()
    with patch.object(arranger.client, "ask_json", AsyncMock(return_value={"phrases": []})):
        result = await arranger.transform_to_bossa(_ir())
    assert validate_intermediate(result.ir) == []
    assert len(result.ir["parts"]["bass"]) > 0
