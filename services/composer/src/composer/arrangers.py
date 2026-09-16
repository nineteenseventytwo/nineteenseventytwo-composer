"""Arranger strategies, selected by configuration.

Two exist, and the plan's **C5** describes them as a progression rather than
alternatives:

``notes``
    Ask the model to rewrite the note lists. What the pipeline did first.
    Measured in **C24**: harmonically unreliable (the source root survived in
    8 bars of 32) and slow (~18 output tokens per event; 577s for 32 bars).

``deterministic``
    Detect the chord from the source and render bass and comping from it by
    rule. No model. The root cannot drift because it is an input. Harmonically
    safe, and a loop: a fixed policy cannot know that a section has been heard
    twice and wants lifting.

``plan``
    The destination. The model reads the form, the chords and how often each
    phrase has been heard, and returns a **plan** — density and bass feel per
    phrase, plus targeted chord substitutions. The library renders it.

The economics are the argument. On the longest score in the corpus the plan
prompt is a few hundred tokens and the response a few hundred more, against
~50,000 output tokens for note-echo. And every choice is drawn from a closed
set or validated against the chord it replaces, so the model cannot invent the
harmony the way it did in **C24** — it is being asked for judgement, never for
the root.
"""

from __future__ import annotations

import logging
import os

from musicxml_tools import arrange_deterministically, count_bars
from musicxml_tools.chords import detect_chords, detect_key
from musicxml_tools.form import detect_form
from musicxml_tools.plan import (
    describe_for_model,
    plan_from_model,
    plan_schema,
    substitution_menu,
)

from composer.llm_client import ChunkOutcome, LLMClient, TransformResult

logger = logging.getLogger(__name__)

DEFAULT_ARRANGER = "deterministic"


class DeterministicArranger:
    """Render bossa parts from chords detected in the source.

    Reports itself as a single successful "chunk" so callers that surface
    per-chunk progress keep working without special-casing the strategy.
    """

    name = "deterministic"

    async def transform_to_bossa(self, ir: dict) -> TransformResult:
        arranged = arrange_deterministically(ir)
        bars = count_bars(ir)
        logger.info("Deterministic arrangement over %d bars", bars)
        return TransformResult(
            ir=arranged,
            outcomes=[ChunkOutcome(first_bar=0, bars=bars, transformed=True)],
        )


PLAN_SYSTEM_PROMPT = """\
You are an arranger producing a chill bossa nova backing track from a game
music transcription. You are given the piece's key, its harmony bar by bar, and
its form — which phrases repeat and how often each has been heard.

You do not write notes. You decide how each phrase is *played*, and the
arranger renders it.

For each phrase choose:
  density  sparse | normal | busy   — how much the comping fills the bar
  bass     root-fifth | walk | pedal | anticipate

Aim for shape. A phrase heard for the third time played exactly as the first is
what makes an arrangement sound like a loop. Build and release: let sections
breathe before a busier one, thin out where the melody is doing the work. The
target is chill, so restraint is usually right and "busy" should be rare.

Some bars list substitutions. **Answer for every one of them** — pick a chord
from that bar's options, or "none" to leave it alone. They are worked out from
the harmony, so any option will fit; you are deciding which colour the moment
wants, not whether it is legal.

Prefer variety across a piece over the same move every time, and mean it when
you say "none" — a turnaround at every phrase end is as mechanical as none at
all. Somewhere between a third and two thirds is usually right.
"""


class PlanArranger:
    """Ask the model how to play the piece, then render its answer."""

    name = "plan"

    def __init__(self, client: LLMClient | None = None):
        self.client = client or LLMClient()

    async def transform_to_bossa(self, ir: dict) -> TransformResult:
        chords = detect_chords(ir)
        if not chords:
            return TransformResult(ir=arrange_deterministically(ir))

        phrases = detect_form(chords)
        description = describe_for_model(chords, phrases, str(detect_key(ir)))
        menu = substitution_menu(chords, phrases)

        try:
            response = await self.client.ask_json(
                system=PLAN_SYSTEM_PROMPT,
                prompt=description,
                schema=plan_schema(menu),
            )
        except Exception as e:  # noqa: BLE001 - any model failure must degrade to
            # the deterministic arrangement rather than lose the piece
            # Fall back to the fixed policy rather than to no arrangement: the
            # deterministic path is a complete, harmonically sound result, so a
            # model failure costs shape rather than the whole piece.
            logger.warning("Plan request failed (%s); using the fixed policy", e)
            return TransformResult(
                ir=arrange_deterministically(ir),
                outcomes=[ChunkOutcome(0, count_bars(ir), False, f"{type(e).__name__}: {e}")],
            )

        plan = plan_from_model(chords, phrases, response)
        for rejection in plan.rejected:
            logger.info("Rejected substitution — %s", rejection)
        logger.info("Plan: %s", plan.describe())

        return TransformResult(
            ir=arrange_deterministically(ir, plan=plan),
            outcomes=[ChunkOutcome(0, count_bars(ir), True)],
        )


def get_arranger(name: str | None = None):
    """Pick an arranger. `COMPOSER_ARRANGER` overrides; default is deterministic."""
    choice = (name or os.environ.get("COMPOSER_ARRANGER", DEFAULT_ARRANGER)).lower()
    if choice == "notes":
        return LLMClient()
    if choice == "deterministic":
        return DeterministicArranger()
    if choice == "plan":
        return PlanArranger()
    raise ValueError(
        f"Unknown arranger {choice!r}; expected 'deterministic', 'plan' or 'notes'"
    )
