"""Run the transform over a set of scores and report how well it arranged them.

    python -m composer.eval_cli examples/input/*.mxl

Evaluates the **model's contribution** rather than the finished file: source IR
against arranged IR, before assembly transposes, folds and re-bars anything.
That keeps the number attributable — a drop here is the model or the prompt,
not the notation layer.

Intermediate representations are written alongside the report so a bad run can
be read afterwards instead of re-run.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from musicxml_tools import parse_score, split_voices, to_intermediate

from composer.evaluate import evaluate
from composer.llm_client import LLMClient


async def _run_one(path: Path, client: LLMClient, out_dir: Path | None) -> dict:
    source = to_intermediate(split_voices(parse_score(path)))

    started = time.time()
    result = await client.transform_to_bossa(source)
    elapsed = time.time() - started

    metrics = evaluate(source, result.ir)

    if out_dir:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{path.stem}.source.json").write_text(json.dumps(source, indent=1))
        (out_dir / f"{path.stem}.arranged.json").write_text(json.dumps(result.ir, indent=1))

    return {
        "score": path.stem,
        "bars": metrics.bars,
        "chunks": f"{result.transformed}/{result.total}",
        "seconds": elapsed,
        "metrics": metrics,
        "failures": [o.reason for o in result.outcomes if not o.transformed],
    }


async def _main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scores", nargs="+", type=Path)
    parser.add_argument("--model", default=None)
    parser.add_argument("--bars-per-chunk", type=int, default=None)
    parser.add_argument("--concurrency", type=int, default=None)
    parser.add_argument("--out", type=Path, default=Path("examples/eval"))
    parser.add_argument("--label", default="")
    args = parser.parse_args(argv)

    client = LLMClient(
        model=args.model,
        bars_per_chunk=args.bars_per_chunk,
        max_concurrency=args.concurrency,
    )

    print(f"model={client.model} bars/chunk={client.bars_per_chunk} "
          f"concurrency={client.max_concurrency} {args.label}".rstrip())
    print(f"{'score':30s} {'bars':>4s} {'chunks':>7s} {'time':>6s} "
          f"{'root=':>6s} {'ground':>6s} {'harm':>5s} {'cover':>6s} {'offs':>5s} {'b/chd':>6s}")

    rows = []
    for path in args.scores:
        row = await _run_one(path, client, args.out)
        m = row["metrics"]
        rows.append(row)
        print(f"{row['score'][:28]:30s} {row['bars']:4d} {row['chunks']:>7s} "
              f"{row['seconds']:5.0f}s {m.root_exact:6.0%} {m.root_grounded:6.0%} "
              f"{m.harmony_fidelity:5.0%} {min(m.coverage.values(), default=0):6.0%} "
              f"{m.offsets_in_bar:5.0%} {m.bars_per_chord:6.1f}")
        for reason in row["failures"][:2]:
            print(f"{'':30s}   ! {reason[:80]}")

    if len(rows) > 1:
        n = len(rows)
        print(f"{'MEAN':30s} {'':4s} {'':>7s} "
              f"{sum(r['seconds'] for r in rows)/n:5.0f}s "
              f"{sum(r['metrics'].root_exact for r in rows)/n:6.0%} "
              f"{sum(r['metrics'].root_present for r in rows)/n:6.0%} "
              f"{sum(r['metrics'].harmony_fidelity for r in rows)/n:5.0%}")
    return 0


def main() -> int:
    return asyncio.run(_main(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
