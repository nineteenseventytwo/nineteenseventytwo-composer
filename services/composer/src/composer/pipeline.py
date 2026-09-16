"""Arrangement pipeline: split → transform → assemble."""

import asyncio
import logging
import math
from pathlib import Path

import music21

from musicxml_tools import parse_score, split_voices, to_intermediate, from_intermediate, assemble_score
from musicxml_tools.assembler import write_score
from musicxml_tools.drums import generate_bossa_drums, generate_bossa_shaker

from composer.arrangers import get_arranger

logger = logging.getLogger(__name__)


async def arrange(input_path: Path, output_path: Path):
    """Run the full bossa arrangement pipeline.

    Steps:
    1. Parse input MusicXML
    2. Split voices (melody, harmony, bass)
    3. Convert to intermediate representation
    4. Send to LLM for bossa transformation
    5. Convert back from intermediate representation
    6. Generate bossa drum track
    7. Assemble and write output MusicXML

    Returns:
        The transformation result, carrying per-chunk outcomes so the caller
        can tell an arrangement from a passthrough (finding C3).
    """
    # Everything except the LLM call is synchronous, CPU-bound work. Running
    # it directly on the event loop serialises concurrent requests and stops
    # /health answering for the duration — which on a Deployment means the
    # liveness probe can fail *because the service is busy*, and the kubelet
    # restarts a pod that was working correctly.
    logger.info("Parsing input score: %s", input_path)
    score = await asyncio.to_thread(parse_score, input_path)

    logger.info("Splitting voices")
    parts = await asyncio.to_thread(split_voices, score)

    logger.info("Converting to intermediate representation")
    ir = await asyncio.to_thread(to_intermediate, parts)

    arranger = get_arranger()
    logger.info("Arranging (%s)", arranger.name if hasattr(arranger, "name") else "notes")
    result = await arranger.transform_to_bossa(ir)
    transformed_ir = result.ir

    logger.info("Converting back from intermediate representation")
    transformed_parts = await asyncio.to_thread(from_intermediate, transformed_ir)

    logger.info("Generating bossa drum track")
    # Count measures from the melody part
    time_signature = ir["metadata"].get("time_signature", "4/4")
    num_measures = len(list(transformed_parts.melody.getElementsByClass("Measure")))
    if num_measures == 0:
        # Fallback only — parts rebuilt from the IR are barred (see _barred).
        # Measure the bar in quarter notes rather than trusting the numerator:
        # 6/8 has six beats but a bar three quarter notes long.
        all_notes = list(transformed_parts.melody.flatten().notesAndRests)
        if all_notes:
            max_offset = max(n.offset + n.quarterLength for n in all_notes)
            bar = float(music21.meter.TimeSignature(time_signature).barDuration.quarterLength)
            num_measures = max(1, math.ceil(max_offset / bar))
        else:
            num_measures = 4

    # Two percussion parts, one per Game Boy channel — the kit on wave, the
    # shaker on noise. See docs/performance-context.md.
    drums = generate_bossa_drums(
        num_measures=num_measures,
        time_signature=time_signature,
    )
    shaker = generate_bossa_shaker(
        num_measures=num_measures,
        time_signature=time_signature,
    )

    logger.info("Assembling output score")
    output_score = await asyncio.to_thread(
        assemble_score, transformed_parts, drums, None, shaker
    )

    logger.info("Writing output: %s", output_path)
    await asyncio.to_thread(write_score, output_score, output_path)

    return result
