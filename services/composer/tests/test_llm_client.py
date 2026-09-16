"""Tests for chunked transformation and its failure reporting."""

import asyncio
import json
from unittest.mock import AsyncMock, patch

import pytest
from musicxml_tools import EXAMPLE, split_by_bars

from composer.llm_client import LLMClient, PayloadTooLarge

# Every chunk must have distinguishable content. Offsets are rebased per chunk,
# so an arrangement of identical bars produces identical chunks and a test
# cannot single one out. The note name cycles every 7 bars while the octave
# steps once per 8-bar chunk, so the two never share a period: each chunk sits
# in its own octave and "D4" identifies exactly one of them.
_NOTES = "CDEFGAB"
_BARS_PER_CHUNK = 8


def _pitch(bar: int) -> str:
    return f"{_NOTES[bar % len(_NOTES)]}{3 + bar // _BARS_PER_CHUNK}"


def _ir(bars: int = 32) -> dict:
    """A schema-valid arrangement spanning `bars` bars of 4/4."""
    return {
        "metadata": {"title": "T", "tempo": 120, "time_signature": "4/4", "pickup": 0.0},
        "parts": {
            "melody": [
                {"pitch": _pitch(b), "duration": 1.0, "offset": float(b * 4)}
                for b in range(bars)
            ],
            "harmony": [
                {"pitches": ["E4", "G4"], "duration": 1.0, "offset": float(b * 4)}
                for b in range(bars)
            ],
            "bass": [{"pitch": "C3", "duration": 1.0, "offset": float(b * 4)} for b in range(bars)],
        },
    }


def _echo(prompt: str, _http=None) -> str:
    """Stand in for the model by returning the payload unchanged."""
    return json.dumps(json.loads(prompt.split("\n\n", 1)[1]))


@pytest.mark.asyncio
async def test_chunks_are_transformed_and_reassembled():
    client = LLMClient(bars_per_chunk=8)
    with patch.object(client, "_chat", AsyncMock(side_effect=_echo)):
        result = await client.transform_to_bossa(_ir())
    assert result.total == 4
    assert result.transformed == 4
    assert result.ir["parts"]["melody"] == _ir()["parts"]["melody"]


@pytest.mark.asyncio
async def test_chunks_run_concurrently_but_reassemble_in_order():
    """Concurrency must not reorder the arrangement.

    ``asyncio.gather`` preserves input order, so chunk N's result stays chunk
    N's however the requests interleave. Returning them slowest-first would
    catch a version that zipped results onto completion order.
    """
    client = LLMClient(bars_per_chunk=8, max_concurrency=4)
    delays = iter([0.04, 0.03, 0.02, 0.01])

    async def slow_echo(prompt: str, _http=None) -> str:
        await asyncio.sleep(next(delays))
        return _echo(prompt)

    with patch.object(client, "_chat", AsyncMock(side_effect=slow_echo)):
        result = await client.transform_to_bossa(_ir())

    assert result.transformed == 4
    assert result.ir["parts"]["melody"] == _ir()["parts"]["melody"]
    assert [o.first_bar for o in result.outcomes] == [0, 8, 16, 24]


@pytest.mark.asyncio
async def test_a_failed_chunk_falls_back_without_losing_the_rest():
    client = LLMClient(bars_per_chunk=8)
    # Keyed on content, not call order: with chunks in flight together the
    # order requests are issued in is not deterministic.
    async def flaky(prompt: str, _http=None) -> str:
        if '"D4"' in prompt:  # octave 4 is unique to the chunk beginning at bar 8
            return "{not json"
        return _echo(prompt)

    with patch.object(client, "_chat", AsyncMock(side_effect=flaky)):
        result = await client.transform_to_bossa(_ir())

    assert result.total == 4
    assert result.transformed == 3
    failed = [o for o in result.outcomes if not o.transformed]
    assert len(failed) == 1 and "JSONDecodeError" in failed[0].reason
    assert failed[0].first_bar == 8
    # the arrangement is still complete — the failed chunk kept its original bars
    assert len(result.ir["parts"]["melody"]) == 32


@pytest.mark.asyncio
async def test_schema_violation_is_reported_not_raised():
    client = LLMClient(bars_per_chunk=32)
    bad = json.dumps({"metadata": {}, "parts": {"melody": {"notes": []}, "harmony": [], "bass": []}})
    with patch.object(client, "_chat", AsyncMock(return_value=bad)):
        result = await client.transform_to_bossa(_ir())
    assert result.transformed == 0
    assert "schema" in result.outcomes[0].reason


def test_oversize_payload_is_refused_rather_than_truncated():
    client = LLMClient(num_ctx=1024, num_predict=512)
    with pytest.raises(PayloadTooLarge):
        client._check_fits("x" * 100_000)


def test_the_prompt_example_is_chunkable():
    assert split_by_bars(EXAMPLE, 1)
