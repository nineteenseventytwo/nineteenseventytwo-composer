# Service: composer

**Role:** HTTP API and pipeline orchestrator
**Language:** Python 3.12
**Framework:** FastAPI + httpx (async)
**Entry point:** `composer.app` → `uvicorn composer.app:app`

## What It Does

Exposes one meaningful endpoint: `POST /arrange`. Takes a MusicXML piano score, runs the full arrangement pipeline, returns a MusicXML bossa arrangement.

## Key Files

### `app.py`
Thin FastAPI shell. Writes the upload to a temp file, calls `arrange()`, returns the result as a file download. Minimal logic — just HTTP plumbing.

### `pipeline.py`
The pipeline function `arrange()`. Calls musicxml-tools for parsing/splitting/assembling, calls `LLMClient` for the style transformation. This is the only file that knows about the full sequence of steps.

### `arrangers.py`
The strategies, selected by `COMPOSER_ARRANGER`. `deterministic` (the default)
needs no model at all; `plan` asks a model how each phrase should be played;
`notes` is the original approach, kept for comparison. Each returns the same
`TransformResult`, so the pipeline does not know which it called.

### `llm_client.py`
HTTP client for Ollama.
- `transform_to_bossa(ir)` — the chunked note-rewriting path
- `ask_json(system, prompt, schema)` — one schema-constrained question, used
  by the plan arranger

Requests are constrained by a JSON schema rather than asked politely for JSON,
which is both more reliable and *faster* than free generation — the grammar
stops the model rambling.

### `evaluate.py`
Compares an arrangement with its source: root grounding, harmonic fidelity,
coverage, harmonic rhythm. Every metric exists because listening caught
something the previous set had passed.

### `eval_cli.py`
`python -m composer.eval_cli examples/input/*.mxl` — runs the transform over a
set of scores and reports how well each was arranged.

## The LLM Call in Detail

```python
response = await client.post(
    f"{self.base_url}/api/chat",
    json={
        "model": self.model,                          # e.g. "llama3:8b"
        "messages": [
            {"role": "system", "content": BOSSA_SYSTEM_PROMPT},  # instructions
            {"role": "user",   "content": prompt},               # the JSON to transform
        ],
        "stream": False,
        "options": {
            "temperature": 0.7,   # some creativity, not too random
            "num_predict": 4096,  # max tokens to generate
        },
    },
)
```

`stream: False` means wait for the full response before returning (simpler for a request/response API).

Temperature 0.7 is a common default — 0 = deterministic/repetitive, 1+ = creative/unreliable. For structured JSON output you'd typically use lower (0.1–0.3) or constrain output format further using Ollama's `format: "json"` option.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `LLM_BASE_URL` | `http://localhost:11434` | Ollama API base URL. Set explicitly in deployment — inference runs off-cluster (D-A) |
| `LLM_MODEL` | `llama3:8b` | Model name |
| `LOG_LEVEL` | `info` | Logging level |

## Running Locally

```bash
cd services/composer
pip install -e ".[dev]"
uvicorn composer.app:app --reload
# Test:
curl -X POST http://localhost:8000/arrange -F "file=@my_score.musicxml" -o result.musicxml
```
