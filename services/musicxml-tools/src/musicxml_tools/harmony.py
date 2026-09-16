"""Assemble a complete arrangement from detected harmony.

The alternative to asking a model to write note lists. Finding **C24**: asked
to *write the notes*, an 8B model produced a textbook bossa bass in the wrong
key — the original root survived in 8 bars of 32 — and cost ~18 output tokens
per event doing it.

Here the chord is **detected from the source** (`chords.py`), so the root is an
input rather than a generation and cannot drift, and the parts are rendered
from it by rule (`comping.py`), because bass and comping are rule-shaped. What
is *not* rule-shaped — which tensions to add, where to substitute, how to
phrase the melody — is what a model should be asked for, on top of this rather
than instead of it.
"""

from __future__ import annotations

from typing import Any

from musicxml_tools.chords import BarChord, detect_chords, detect_key
from musicxml_tools.comping import DEFAULT_PATTERN, PATTERNS, render_bass, render_comp
from musicxml_tools.form import detect_form, summarise
from musicxml_tools.plan import (
    ArrangementPlan,
    describe_for_model,
    plan_from_form,
    plan_from_model,
    plan_schema,
)

__all__ = [
    "DEFAULT_PATTERN",
    "PATTERNS",
    "ArrangementPlan",
    "BarChord",
    "arrange_deterministically",
    "describe_for_model",
    "detect_chords",
    "detect_form",
    "detect_key",
    "plan_from_form",
    "plan_from_model",
    "plan_schema",
    "render_bass",
    "render_comp",
    "summarise",
]


def arrange_deterministically(
    ir: dict[str, Any],
    pattern: str | None = None,
    plan: ArrangementPlan | None = None,
) -> dict[str, Any]:
    """A complete arrangement with no model involved.

    A `plan` decides how each bar is played; one is derived from the detected
    form when none is supplied. That parameter is the seam the plan arranger
    fits into — the model produces a plan, this renders it.

    The melody is carried through **untouched**. That is a decision, not an
    omission: it is the tune, it is the one part the source already has right,
    and it is the part played live — so phrasing is the player's to add rather
    than the tool's to impose.
    """
    chords = detect_chords(ir)
    plan = plan or plan_from_form(chords)
    chords = plan.apply_to(chords)
    return {
        "metadata": dict(ir.get("metadata", {})),
        "parts": {
            "melody": list(ir["parts"].get("melody", [])),
            "harmony": render_comp(
                chords, ir, pattern or DEFAULT_PATTERN, plan.density_by_bar
            ),
            "bass": render_bass(chords, ir, plan.bass_by_bar),
        },
    }
