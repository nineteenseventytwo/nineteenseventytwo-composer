"""JSON Schema for the intermediate representation — one definition, three uses.

The shape of the IR is defined here and nowhere else. It is used to:

1. **constrain decoding** — passed as Ollama's ``format`` so the model cannot
   emit anything that is not valid IR, rather than being asked in capital
   letters not to;
2. **validate a response** before it reaches ``from_intermediate``;
3. **render the worked example** in the prompt.

Finding C2 was a worked example in the prompt that taught a shape the parser
could not read — ``{"parts": {"bass": {"notes": [...]}}}`` where the code
produces ``{"parts": {"bass": [...]}}``. A model that *obeyed* the example
crashed the pipeline with an uncaught ``AttributeError``. Hand-maintaining that
agreement across three places is what failed; deriving all three from one
definition is the fix, and ``test_schema`` asserts the example still conforms.
"""

from __future__ import annotations

import json
from typing import Any

# music21 emits flats as "-" (``A-4``) but accepts "b" as well (``Ab4``), so
# both spellings are allowed here. Verified against music21 10.5.
PITCH_PATTERN = r"^[A-Ga-g][#b\-]*[0-9]$"

_DURATION = {
    "type": "number",
    "exclusiveMinimum": 0,
    "description": "Length in quarter notes.",
}
_OFFSET = {
    "type": "number",
    "minimum": 0,
    "description": "Start position in quarter notes from the beginning of the part.",
}


def _note() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["pitch", "duration", "offset"],
        "additionalProperties": False,
        "properties": {
            "pitch": {"type": "string", "pattern": PITCH_PATTERN},
            "duration": _DURATION,
            "offset": _OFFSET,
        },
    }


def _chord() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["pitches", "duration", "offset"],
        "additionalProperties": False,
        "properties": {
            "pitches": {
                "type": "array",
                "minItems": 1,
                "items": {"type": "string", "pattern": PITCH_PATTERN},
            },
            "duration": _DURATION,
            "offset": _OFFSET,
        },
    }


def _rest() -> dict[str, Any]:
    return {
        "type": "object",
        "required": ["rest", "duration", "offset"],
        "additionalProperties": False,
        "properties": {
            "rest": {"const": True},
            "duration": _DURATION,
            "offset": _OFFSET,
        },
    }


def _line() -> dict[str, Any]:
    """A monophonic part: melody and bass carry one pitch at a time."""
    return {"type": "array", "items": {"anyOf": [_note(), _rest()]}}


def _voicing() -> dict[str, Any]:
    """Harmony, which may carry chords.

    Chords stay in the score even though a Game Boy pulse channel is
    monophonic — LSDj Tables supply the chord character at playback. See
    docs/performance-context.md.
    """
    return {"type": "array", "items": {"anyOf": [_chord(), _note(), _rest()]}}


def intermediate_schema() -> dict[str, Any]:
    """The JSON Schema for a complete intermediate representation."""
    return {
        "type": "object",
        "required": ["metadata", "parts"],
        "additionalProperties": False,
        "properties": {
            "metadata": {
                "type": "object",
                "description": "Preserved unchanged from the input.",
                "properties": {
                    "title": {"type": "string"},
                    "tempo": {"type": "number"},
                    "key": {"type": "string"},
                    "key_signature": {"type": "string"},
                    "time_signature": {"type": "string"},
                    "pickup": {"type": "number", "minimum": 0},
                },
            },
            "parts": {
                "type": "object",
                "required": ["melody", "harmony", "bass"],
                "additionalProperties": False,
                "properties": {
                    "melody": _line(),
                    "harmony": _voicing(),
                    "bass": _line(),
                },
            },
        },
    }


# A worked example for the prompt. Two bars of idiomatic bossa: a bass that
# alternates root and fifth with anticipation, rootless harmony voicings placed
# in the comping register, and a melody that sits behind the beat.
#
# It is deliberately short. Its job is to teach the *shape* and the *style*,
# not to be copied — and every token spent here is a token not spent on the
# score (finding C5).
EXAMPLE: dict[str, Any] = {
    "metadata": {
        "title": "Example",
        "tempo": 132,
        "key": "F major",
        "key_signature": "F major",
        "time_signature": "4/4",
        "pickup": 0.0,
    },
    "parts": {
        "melody": [
            {"pitch": "A4", "duration": 1.5, "offset": 0.0},
            {"pitch": "G4", "duration": 0.5, "offset": 1.5},
            {"rest": True, "duration": 1.0, "offset": 2.0},
            {"pitch": "F4", "duration": 1.0, "offset": 3.0},
        ],
        "harmony": [
            {"pitches": ["A3", "D4", "G4"], "duration": 1.5, "offset": 0.0},
            {"pitches": ["A3", "D4", "G4"], "duration": 0.5, "offset": 1.5},
            {"pitches": ["A-3", "D-4", "G-4"], "duration": 1.5, "offset": 2.0},
            {"pitches": ["A-3", "D-4", "G-4"], "duration": 0.5, "offset": 3.5},
        ],
        "bass": [
            {"pitch": "F2", "duration": 1.0, "offset": 0.0},
            {"pitch": "C3", "duration": 0.5, "offset": 1.5},
            {"pitch": "F2", "duration": 1.0, "offset": 2.0},
            {"pitch": "C3", "duration": 0.5, "offset": 3.5},
        ],
    },
}


def example_json(indent: int = 2) -> str:
    """The worked example, rendered for inclusion in a prompt."""
    return json.dumps(EXAMPLE, indent=indent)


def validate_intermediate(data: Any) -> list[str]:
    """Return a list of human-readable schema violations; empty means valid.

    Used instead of the previous check, which only tested that the keys
    ``parts`` and ``metadata`` existed. A response with the right keys and the
    wrong shape passed that check and then died inside ``from_intermediate``
    with an uncaught ``AttributeError`` (finding C3).
    """
    try:
        import jsonschema
    except ImportError:  # pragma: no cover - dependency is declared
        return []

    validator = jsonschema.Draft202012Validator(intermediate_schema())
    return [
        f"{'/'.join(str(p) for p in error.path) or '<root>'}: {error.message}"
        for error in sorted(validator.iter_errors(data), key=lambda e: list(e.path))
    ]
