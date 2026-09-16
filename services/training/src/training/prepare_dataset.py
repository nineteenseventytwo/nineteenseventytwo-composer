"""Prepare training dataset from MusicXML input/output pairs and reference scores."""

import argparse
import json
import logging
from pathlib import Path

from musicxml_tools import parse_score, split_voices, to_intermediate

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are an expert jazz arranger specializing in bossa nova. "
    "Transform the given musical arrangement into bossa nova style. "
    "Return ONLY valid JSON in the same format."
)

REFERENCE_SYSTEM_PROMPT = (
    "You are an expert jazz arranger specializing in bossa nova. "
    "You have deep knowledge of bossa nova voicings, bass patterns, "
    "rhythmic feel, and arrangement conventions."
)


def prepare_pair(input_path: Path, output_path: Path) -> dict:
    """Convert one input/output MusicXML pair into a training example.

    Args:
        input_path: Path to the original piano score.
        output_path: Path to the bossa arrangement.

    Returns:
        A training example dict with system/user/assistant messages.
    """
    # Parse and convert both to intermediate representation
    input_score = parse_score(input_path)
    input_parts = split_voices(input_score)
    input_ir = to_intermediate(input_parts)

    output_score = parse_score(output_path)
    output_parts = split_voices(output_score)
    output_ir = to_intermediate(output_parts)

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Transform this arrangement to bossa nova style. "
                    "Return ONLY the transformed JSON:\n\n"
                    + json.dumps(input_ir, indent=2)
                ),
            },
            {
                "role": "assistant",
                "content": json.dumps(output_ir, indent=2),
            },
        ]
    }


def prepare_reference(musicxml_path: Path) -> dict:
    """Convert a single bossa reference score into a style training example.

    The model learns what idiomatic bossa nova looks like in the intermediate
    representation, without needing a corresponding "before" version.

    Args:
        musicxml_path: Path to a bossa nova MusicXML score.

    Returns:
        A training example dict with system/user/assistant messages.
    """
    score = parse_score(musicxml_path)
    parts = split_voices(score)
    ir = to_intermediate(parts)

    return {
        "messages": [
            {"role": "system", "content": REFERENCE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    "Analyze this bossa nova arrangement. Describe the stylistic "
                    "choices in the voicings, bass line, and rhythm, then reproduce "
                    "the arrangement as JSON:\n\n"
                    + json.dumps(ir, indent=2)
                ),
            },
            {
                "role": "assistant",
                "content": (
                    "This arrangement demonstrates classic bossa nova conventions:\n"
                    "- Bass: root-fifth pattern with syncopation\n"
                    "- Harmony: rootless voicings with 9ths, 7ths, and 13ths\n"
                    "- Rhythm: anticipations and displaced accents\n\n"
                    + json.dumps(ir, indent=2)
                ),
            },
        ]
    }


def prepare_dataset(
    data_dir: Path,
    output_path: Path,
    reference_dir: Path | None = None,
) -> None:
    """Prepare the full training dataset from pairs and optional reference scores.

    Expected structure:
        data_dir/
            song1/
                input.musicxml
                output.musicxml
            song2/
                input.musicxml
                output.musicxml

        reference_dir/ (optional)
            desafinado.musicxml
            corcovado.musicxml
            ...

    Args:
        data_dir: Directory containing song pair subdirectories.
        output_path: Path to write the JSONL training file.
        reference_dir: Optional directory of bossa MusicXML reference scores.
    """
    examples = []

    # Paired transformation examples
    for song_dir in sorted(data_dir.iterdir()):
        if not song_dir.is_dir():
            continue

        input_file = song_dir / "input.musicxml"
        output_file = song_dir / "output.musicxml"

        if not input_file.exists() or not output_file.exists():
            logger.warning("Skipping %s: missing input.musicxml or output.musicxml", song_dir.name)
            continue

        try:
            example = prepare_pair(input_file, output_file)
            examples.append(example)
            logger.info("Prepared pair: %s", song_dir.name)
        except Exception:
            logger.exception("Failed to prepare pair %s", song_dir.name)

    # Reference style examples
    if reference_dir and reference_dir.is_dir():
        for ref_file in sorted(reference_dir.glob("*.musicxml")):
            try:
                example = prepare_reference(ref_file)
                examples.append(example)
                logger.info("Prepared reference: %s", ref_file.name)
            except Exception:
                logger.exception("Failed to prepare reference %s", ref_file.name)

    # Write JSONL
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        for example in examples:
            f.write(json.dumps(example) + "\n")

    pair_count = sum(1 for e in examples if e["messages"][0]["content"] == SYSTEM_PROMPT)
    ref_count = len(examples) - pair_count
    logger.info(
        "Wrote %d training examples (%d pairs, %d references) to %s",
        len(examples), pair_count, ref_count, output_path,
    )


def main():
    parser = argparse.ArgumentParser(description="Prepare training dataset from MusicXML pairs and references")
    parser.add_argument("--data-dir", type=Path, required=True, help="Directory of song pairs")
    parser.add_argument("--reference-dir", type=Path, default=None, help="Directory of bossa reference MusicXML scores")
    parser.add_argument("--output", type=Path, default=Path("data/training.jsonl"))
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    prepare_dataset(args.data_dir, args.output, args.reference_dir)


if __name__ == "__main__":
    main()
