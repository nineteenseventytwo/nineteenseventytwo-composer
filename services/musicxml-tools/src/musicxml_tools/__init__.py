"""musicxml-tools: MusicXML parsing, voice splitting, and score assembly."""

from musicxml_tools.parser import parse_score
from musicxml_tools.splitter import split_voices
from musicxml_tools.intermediate import to_intermediate, from_intermediate
from musicxml_tools.assembler import assemble_score
from musicxml_tools.chunking import Chunk, count_bars, merge_chunks, split_by_bars
from musicxml_tools.chords import detect_key
from musicxml_tools.comping import PATTERNS, rootless_voicing
from musicxml_tools.harmony import (
    BarChord,
    arrange_deterministically,
    detect_chords,
    render_bass,
    render_comp,
)
from musicxml_tools.schema import (
    EXAMPLE,
    example_json,
    intermediate_schema,
    validate_intermediate,
)

__all__ = [
    "parse_score",
    "split_voices",
    "to_intermediate",
    "from_intermediate",
    "assemble_score",
    "BarChord",
    "Chunk",
    "arrange_deterministically",
    "detect_chords",
    "detect_key",
    "rootless_voicing",
    "PATTERNS",
    "render_bass",
    "render_comp",
    "count_bars",
    "merge_chunks",
    "split_by_bars",
    "EXAMPLE",
    "example_json",
    "intermediate_schema",
    "validate_intermediate",
]
