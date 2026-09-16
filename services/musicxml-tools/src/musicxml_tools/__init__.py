"""musicxml-tools: MusicXML parsing, voice splitting, and score assembly."""

from musicxml_tools.assembler import assemble_score
from musicxml_tools.chords import detect_key
from musicxml_tools.chunking import Chunk, count_bars, merge_chunks, split_by_bars
from musicxml_tools.comping import PATTERNS, rootless_voicing
from musicxml_tools.harmony import (
    BarChord,
    arrange_deterministically,
    detect_chords,
    render_bass,
    render_comp,
)
from musicxml_tools.intermediate import from_intermediate, to_intermediate
from musicxml_tools.parser import parse_score
from musicxml_tools.schema import (
    EXAMPLE,
    example_json,
    intermediate_schema,
    validate_intermediate,
)
from musicxml_tools.splitter import split_voices

__all__ = [
    "EXAMPLE",
    "PATTERNS",
    "BarChord",
    "Chunk",
    "arrange_deterministically",
    "assemble_score",
    "count_bars",
    "detect_chords",
    "detect_key",
    "example_json",
    "from_intermediate",
    "intermediate_schema",
    "merge_chunks",
    "parse_score",
    "render_bass",
    "render_comp",
    "rootless_voicing",
    "split_by_bars",
    "split_voices",
    "to_intermediate",
    "validate_intermediate",
]
