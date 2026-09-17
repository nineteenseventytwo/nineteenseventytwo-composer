"""LLM client for bossa transformations via Ollama API."""

import asyncio
import json
import logging
import os
from dataclasses import dataclass, field

import httpx
from musicxml_tools import (
    Chunk,
    example_json,
    intermediate_schema,
    merge_chunks,
    split_by_bars,
    validate_intermediate,
)

logger = logging.getLogger(__name__)

# Localhost, not an in-cluster service name. Inference runs off-cluster on the
# GPU host (D-A), so there is no `llm-server` Service to resolve — that name
# survived from the rejected design where Ollama was a cluster workload. In
# deployment this is always set explicitly; localhost is what makes a developer
# with Ollama running work without configuration.
DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_MODEL = "llama3.1:8b"

# Ollama applies a small default context window — 2048 in older builds, 4096 in
# recent ones — and **silently discards the overflow**. Left unset, a score is
# truncated with no error and the model answers from the opening bars
# (finding C4). Set it explicitly, and note that `num_predict` is drawn from
# *within* `num_ctx` rather than in addition to it: a generous num_predict
# under a small num_ctx is silently a small num_predict.
DEFAULT_NUM_CTX = 8192
DEFAULT_NUM_PREDICT = 4096

# Bars per request. Eight is a phrase, which keeps the musical unit intact, and
# on the reference corpus the largest chunk comes to ~3,000 tokens against a
# 4,096 budget. A chunk that still does not fit is halved, down to this floor:
# unbounded subdivision would quietly produce one-bar fragments with no context
# to arrange against, which is worse than failing (C4).
# Four bars, measured rather than guessed. Echoing note lists costs roughly
# **18 output tokens per event**: a 2-bar chunk of 63 events produced 1,138
# tokens. Eight bars is ~190 events ≈ 3,400 tokens, close enough to the 4,096
# cap that some chunks truncate mid-array — which arrives as a confusing
# JSONDecodeError rather than as "too long".
DEFAULT_BARS_PER_CHUNK = 4
MIN_BARS_PER_CHUNK = 2

# Concurrency helps less than it looks. Generation is memory-bandwidth bound
# and a single GPU is already saturated by one stream, so parallel requests
# mostly make each other slower: three in flight turned ~120s chunks into
# timeouts. Two overlaps prompt processing with generation without starving
# either. The server-side ceiling is `OLLAMA_NUM_PARALLEL` and VRAM.
DEFAULT_MAX_CONCURRENCY = 2

# A 2,000-token generation at ~45 tok/s is already ~45s before any queuing.
# The previous 120s was tight enough to turn a slow chunk into a failed one.
DEFAULT_TIMEOUT_SECONDS = 300.0

# Rough characters-per-token for JSON of this shape. Only used to refuse
# oversized payloads before sending, so an approximation is adequate — it needs
# to be conservative, not exact.
_CHARS_PER_TOKEN = 4


@dataclass
class ChunkOutcome:
    """What happened to one chunk."""

    first_bar: int
    bars: int
    transformed: bool
    reason: str = ""


@dataclass
class TransformResult:
    """The arrangement, plus an honest account of how much of it was arranged.

    Returning only the IR is what let a total failure look like a success: the
    caller got a well-formed arrangement back and had no way to tell that none
    of it had been transformed (finding C3).
    """

    ir: dict
    outcomes: list[ChunkOutcome] = field(default_factory=list)

    @property
    def transformed(self) -> int:
        return sum(1 for o in self.outcomes if o.transformed)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def ratio(self) -> float:
        return self.transformed / self.total if self.total else 0.0

    def summary(self) -> str:
        return f"{self.transformed}/{self.total} chunks transformed"


class TruncatedResponse(RuntimeError):
    """The model hit its output cap mid-answer.

    Named rather than left to surface as a JSON parse error: constrained
    decoding guarantees well-formed JSON *if it finishes*, so a broken document
    means it ran out of room. "Expecting ',' delimiter: line 653" sends you
    looking at the schema; "truncated at 4096 tokens" tells you to shorten the
    chunk.
    """


class PayloadTooLarge(RuntimeError):
    """The request would not fit in the model's context window.

    Raised rather than sending, because the failure being prevented is a
    *silent* one: Ollama truncates oversize input without complaint, and the
    result looks like a plausible answer computed from a fragment.
    """


BOSSA_SYSTEM_PROMPT = f"""\
You are an expert jazz arranger specializing in bossa nova. You receive a JSON \
representation of a musical arrangement with melody, harmony, and bass parts.

Your task is to transform each part to bossa nova style:

**Bass**: Convert to bossa bass pattern. Use root-fifth movement with syncopation. \
Typical pattern: root on beat 1, fifth on the and-of-2, with occasional chromatic \
approach notes. Keep it simple and grooving.

**Harmony**: Apply bossa voicings. Use rootless voicings (drop the root since bass \
has it). Add 9ths, 7ths, and 13ths where appropriate. Keep voicings in the middle \
register. Use the classic bossa comping rhythm (syncopated, anticipating beats).

**Melody**: Keep the original melody mostly intact but add bossa phrasing. This means \
slight rhythmic displacement (anticipations), occasional grace notes, and breath marks. \
The melody should feel relaxed and behind the beat.

The target is a **chill** arrangement. Thinning the original out is usually \
right; the source material is often busy, and restraint is the point.

Here is a short example in the exact format you must return. Use it as a \
stylistic reference, not as content to copy:

```json
{example_json()}
```

Return the transformed arrangement in the same format. Preserve the metadata \
section unchanged.\
"""


class LLMClient:
    """Client for communicating with the Ollama LLM server."""

    name = "notes"

    def __init__(
        self,
        base_url: str | None = None,
        model: str | None = None,
        num_ctx: int | None = None,
        num_predict: int | None = None,
        bars_per_chunk: int | None = None,
        max_concurrency: int | None = None,
        timeout: float | None = None,
    ):
        self.base_url = base_url or os.environ.get("LLM_BASE_URL", DEFAULT_BASE_URL)
        self.model = model or os.environ.get("LLM_MODEL", DEFAULT_MODEL)
        self.num_ctx = num_ctx or int(os.environ.get("LLM_NUM_CTX", DEFAULT_NUM_CTX))
        self.num_predict = num_predict or int(
            os.environ.get("LLM_NUM_PREDICT", DEFAULT_NUM_PREDICT)
        )
        self.bars_per_chunk = bars_per_chunk or int(
            os.environ.get("LLM_BARS_PER_CHUNK", DEFAULT_BARS_PER_CHUNK)
        )
        self.max_concurrency = max_concurrency or int(
            os.environ.get("LLM_MAX_CONCURRENCY", DEFAULT_MAX_CONCURRENCY)
        )
        self.timeout = timeout or float(
            os.environ.get("LLM_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)
        )

    async def transform_to_bossa(self, ir: dict) -> TransformResult:
        """Transform an arrangement to bossa style, one section at a time.

        Whole-score transformation is impossible on real input — every score in
        the reference corpus is larger than the model can emit (C5) — so the
        arrangement is split into bar-aligned chunks, each transformed
        independently, and reassembled. A chunk that fails falls back to its
        original content, so one bad section costs eight bars rather than the
        whole piece.
        """
        chunks = split_by_bars(ir, self.bars_per_chunk)
        if not chunks:
            return TransformResult(ir=ir)

        # Chunks are independent, so run them together rather than in sequence.
        # One HTTP client for the batch: a new connection per chunk wastes the
        # pool that concurrency exists to use.
        limit = asyncio.Semaphore(self.max_concurrency)

        async with httpx.AsyncClient(timeout=self.timeout) as http:

            async def run(chunk: Chunk) -> tuple[dict, str]:
                async with limit:
                    return await self._transform_chunk(chunk, http)

            # gather preserves input order, so chunk N's result stays chunk N's.
            transformed = await asyncio.gather(*(run(c) for c in chunks))

        results = [
            Chunk(ir=ir_out, start=c.start, first_bar=c.first_bar, bars=c.bars)
            for c, (ir_out, _) in zip(chunks, transformed)
        ]
        outcomes = [
            ChunkOutcome(
                first_bar=c.first_bar,
                bars=c.bars,
                transformed=not reason,
                reason=reason,
            )
            for c, (_, reason) in zip(chunks, transformed)
        ]

        merged = merge_chunks(results, ir["metadata"])
        result = TransformResult(ir=merged, outcomes=outcomes)
        logger.info("Bossa transformation: %s", result.summary())
        return result

    async def _transform_chunk(
        self, chunk: Chunk, http: httpx.AsyncClient | None = None
    ) -> tuple[dict, str]:
        """Transform one chunk. Returns (ir, failure reason); reason empty on success."""
        prompt = self._prompt_for(chunk.ir)

        try:
            self._check_fits(prompt)
        except PayloadTooLarge as e:
            return chunk.ir, str(e)

        try:
            response = await self._chat(prompt, http)
            transformed = json.loads(response)
        except TruncatedResponse as e:
            return chunk.ir, str(e)
        except (httpx.HTTPError, json.JSONDecodeError, KeyError, TypeError) as e:
            # KeyError and TypeError deliberately included: an Ollama error
            # payload has no "message" key, which the previous handler missed
            # and which surfaced as a 500 rather than a fallback.
            return chunk.ir, f"{type(e).__name__}: {e}"

        errors = validate_intermediate(transformed)
        if errors:
            # Shape, not just keys. The previous check asked only whether
            # "parts" and "metadata" existed, so a well-keyed but wrongly
            # shaped response passed it and died inside from_intermediate (C3).
            return chunk.ir, f"schema: {errors[0]}"

        return transformed, ""

    def _prompt_for(self, ir: dict) -> str:
        # Compact separators, not indent=2. Pretty-printing the payload roughly
        # **doubles** its token count — 19,898 against 10,392 on the reference
        # score — and the model gains nothing from the whitespace.
        return (
            "Transform this arrangement to bossa nova style. "
            "Return ONLY the transformed JSON:\n\n"
            + json.dumps(ir, separators=(",", ":"))
        )

    def _check_fits(self, prompt: str) -> None:
        """Refuse a request that cannot fit, rather than letting it truncate."""
        estimated = (len(prompt) + len(BOSSA_SYSTEM_PROMPT)) // _CHARS_PER_TOKEN
        budget = self.num_ctx - self.num_predict
        if estimated > budget:
            raise PayloadTooLarge(
                f"~{estimated} prompt tokens exceeds the {budget} available "
                f"(num_ctx {self.num_ctx} less num_predict {self.num_predict})"
            )

    async def ask_json(self, system: str, prompt: str, schema: dict) -> dict:
        """One schema-constrained question, one parsed answer.

        Separate from `transform_to_bossa` because it carries none of the
        chunking machinery: a plan is small enough to ask for in a single
        request, which is most of the point of asking for a plan.
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json={
                    "model": self.model,
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                    "stream": False,
                    "format": schema,
                    "options": {
                        "temperature": 0.7,
                        "num_ctx": self.num_ctx,
                        "num_predict": self.num_predict,
                    },
                },
            )
            response.raise_for_status()
            data = response.json()

        if data.get("done_reason") == "length":
            raise TruncatedResponse(
                f"plan truncated at {data.get('eval_count', self.num_predict)} tokens"
            )
        return json.loads(data["message"]["content"])

    async def _chat(self, prompt: str, http: httpx.AsyncClient | None = None) -> str:
        """Send a chat request to Ollama.

        Args:
            prompt: The user prompt.
            http: An open client to reuse; one is created if not supplied.

        Returns:
            The model's response text.
        """
        if http is None:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                return await self._post(client, prompt)
        return await self._post(http, prompt)

    async def _post(self, client: httpx.AsyncClient, prompt: str) -> str:
        response = await client.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": [
                    {"role": "system", "content": BOSSA_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "stream": False,
                # Constrained decoding against the generated schema. This
                # removes the "returned prose / fenced markdown / almost
                # JSON" failure class by construction rather than by
                # asking for it in capital letters (C2, D-C).
                "format": intermediate_schema(),
                "options": {
                    "temperature": 0.7,
                    "num_ctx": self.num_ctx,
                    "num_predict": self.num_predict,
                },
            },
            )
        response.raise_for_status()
        data = response.json()

        if data.get("done_reason") == "length":
            raise TruncatedResponse(
                f"output truncated at {data.get('eval_count', self.num_predict)} tokens "
                f"(num_predict {self.num_predict}); reduce bars_per_chunk"
            )

        return data["message"]["content"]
