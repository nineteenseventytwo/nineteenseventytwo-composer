# System Architecture

## What This System Does

You've built an AI-powered music arranger. Feed it a piano score in MusicXML format and it returns a full bossa nova arrangement with four parts: alto sax melody, piano harmony, bass, and drums.

That's the product. Under the hood it's a pipeline that breaks a problem too complex for deterministic rules into a part that rules *can* solve (music parsing), a part that a language model handles (style transformation), and a part rules solve again (reassembly and drums).

```
[Piano MusicXML] → [musicxml-tools] → [JSON] → [LLM] → [JSON] → [musicxml-tools] → [Arrangement MusicXML]
```

## Services

### composer
The FastAPI web service. Its only job is to accept a file upload, run the pipeline, and return the result. Think of it as the outer shell — HTTP in, HTTP out.

### musicxml-tools
A Python library (not a web service). Handles everything music-theory-aware that doesn't require AI:
- Parsing MusicXML into Python objects via [music21](https://web.mit.edu/music21/)
- Splitting a piano score into melody, harmony, and bass voices
- Converting music21 objects ↔ compact JSON (the "intermediate representation")
- Generating the bossa drum pattern algorithmically

### llm-server
Runs [Ollama](https://ollama.ai/) on the GPU node (RTX 4060). Serves the LLM over HTTP on port 11434. The composer service calls it at `/api/chat`. This is off-the-shelf infrastructure — no custom code.

### training
Scripts to fine-tune the LLM on bossa arrangement examples. Not used in the live pipeline — this is for improving the model over time using human-curated input/output MusicXML pairs.

---

## The Key Design Decision: Intermediate Representation

The LLM doesn't see or produce MusicXML. MusicXML is verbose XML intended for notation software — a single note spans ~15 lines. Feeding that to an LLM wastes context window and produces unreliable output.

Instead, `musicxml-tools` converts the score to a compact JSON format first:

```json
{
  "metadata": { "title": "...", "key": "C major", "tempo": 120, "time_signature": "4/4" },
  "parts": {
    "melody": [
      { "pitch": "G4", "duration": 1.0, "offset": 0.0 },
      { "rest": true, "duration": 0.5, "offset": 1.0 }
    ],
    "harmony": [
      { "pitches": ["E3", "G3", "B3"], "duration": 2.0, "offset": 0.0 }
    ],
    "bass": [
      { "pitch": "C2", "duration": 1.0, "offset": 0.0 }
    ]
  }
}
```

The LLM receives this JSON and returns JSON in the same shape, with notes transformed to bossa style. This is a **general pattern** you'll use everywhere with LLMs: define a structured intermediate format, validate the output strictly, and fall back gracefully.

---

## Data Flow

```
POST /arrange (MusicXML file)
  │
  ▼
pipeline.arrange()
  │
  ├─ parse_score()          ← music21 parses MusicXML → Score object
  │
  ├─ split_voices()         ← Top notes → melody, middle → harmony, bottom → bass
  │
  ├─ to_intermediate()      ← Converts music21 objects → compact JSON dict
  │
  ├─ LLMClient.transform_to_bossa()
  │     └─ POST /api/chat to Ollama
  │          System: "You are a bossa nova arranger..."
  │          User: the JSON dict
  │          Returns: transformed JSON dict
  │
  ├─ from_intermediate()    ← Converts JSON back → music21 Part objects
  │
  ├─ generate_bossa_drums() ← Algorithmic drum pattern (no LLM)
  │
  └─ assemble_score()       ← Combines parts → Score, writes MusicXML
```

---

## Failure Handling

If Ollama is unreachable or returns invalid JSON, `LLMClient` catches the error and returns the original IR unchanged. The pipeline still produces output — just without the bossa transformation. This is intentional: **AI steps should be optional enhancements, not hard dependencies**, wherever possible.

```python
except (httpx.HTTPError, json.JSONDecodeError) as e:
    logger.error("LLM transformation failed: %s", e)
    logger.info("Falling back to original arrangement")
    return ir
```

---

## Infrastructure

The service runs on a Raspberry Pi Kubernetes cluster, with the LLM served from the GPU node (RTX 4060, 8GB VRAM). Llama 3 8B at Q4/Q8 quantization fits comfortably in 5–6GB VRAM.

See `infra/` for the Kubernetes manifests and Ansible playbooks.
