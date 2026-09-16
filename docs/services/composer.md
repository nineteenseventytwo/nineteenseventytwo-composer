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

### `llm_client.py`
HTTP client for Ollama. Two methods:
- `transform_to_bossa(ir)` — the public API: send JSON, get JSON back
- `_chat(prompt)` — private: sends the actual HTTP request to `/api/chat`

The system prompt lives here — it's the set of instructions that tells the LLM what role to play and what to do. This is called **prompt engineering**. The prompt explains bossa bass patterns, chord voicings, and melody phrasing in musical terms that the model (trained on text including music theory) understands.

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
| `LLM_BASE_URL` | `http://llm-server:11434` | Ollama API base URL |
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
