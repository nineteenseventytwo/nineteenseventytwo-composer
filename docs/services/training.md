# Service: training

**Role:** Fine-tune the LLM on bossa arrangement examples
**Not part of the live pipeline** — run manually to improve the model over time

## What It Does

Two scripts:
1. `prepare_dataset.py` — converts MusicXML input/output pairs into a JSONL training file
2. `train.py` — fine-tunes a base model using QLoRA, saves a LoRA adapter

## Training Data Format

Two types of training examples are supported:

### Transformation pairs (input → output)
Each example is a three-turn conversation in the same format the live pipeline uses:

```json
{
  "messages": [
    {"role": "system",    "content": "You are a bossa nova arranger..."},
    {"role": "user",      "content": "Transform this...\n{input_ir_json}"},
    {"role": "assistant", "content": "{output_ir_json}"}
  ]
}
```

The model learns: given this system prompt and this musical JSON as input, produce that musical JSON as output. You provide the input/output pairs as MusicXML files (plain piano version → hand-arranged bossa version).

### Reference scores (style library)
Bossa MusicXML scores without a corresponding "before" version. These teach the model what idiomatic bossa sounds like:

```json
{
  "messages": [
    {"role": "system",    "content": "You are an expert jazz arranger..."},
    {"role": "user",      "content": "Analyze this bossa nova arrangement...\n{bossa_ir_json}"},
    {"role": "assistant", "content": "This demonstrates classic bossa conventions...\n{bossa_ir_json}"}
  ]
}
```

Pairs teach the model *how to transform*. References teach it *what good bossa sounds like*. Use both together for best results.

## Fine-Tuning Concepts

### Why Fine-Tune?
The base Llama 3 8B model understands music theory from its pretraining data, but it hasn't specifically learned to transform arbitrary chord progressions to bossa voicings on demand. Fine-tuning on curated examples makes it more reliable and consistent for this specific task.

### LoRA (Low-Rank Adaptation)
Training all 8 billion parameters is impractical on a single RTX 4060. LoRA adds small "adapter" weight matrices to specific layers (the attention layers: `q_proj`, `k_proj`, `v_proj`, `o_proj`) and only trains those. The rest of the model is frozen.

The `r=16` parameter controls adapter size — higher r = more trainable parameters = more capacity but slower training and larger adapter file. `lora_alpha=32` is a scaling factor (conventionally set to 2× r).

### QLoRA (Quantized LoRA)
The base model weights are loaded in 4-bit via `BitsAndBytesConfig`, reducing memory from ~16GB to ~5GB. The LoRA adapters are trained in higher precision. This is what makes fine-tuning an 8B model feasible on 8GB VRAM.

### Training Parameters (in `train.py`)
| Parameter | Value | Meaning |
|---|---|---|
| `num_train_epochs` | 3 | Full passes through the dataset |
| `per_device_train_batch_size` | 1 | One example at a time (VRAM limited) |
| `gradient_accumulation_steps` | 4 | Accumulate before updating — effective batch size = 4 |
| `learning_rate` | 2e-4 | How fast to adjust weights |
| `fp16` | True | 16-bit floats for activations (saves memory) |
| `max_seq_length` | 8192 | Max tokens per training example |

## Workflow

```
1. Collect MusicXML pairs in data/songs/:
   data/songs/
     girl-from-ipanema/
       input.musicxml    ← plain piano score
       output.musicxml   ← hand-arranged bossa version
     corcovado/
       input.musicxml
       output.musicxml

2. Collect bossa reference scores in data/references/:
   data/references/
     desafinado.musicxml      ← any bossa score (no "before" needed)
     wave.musicxml
     so-danco-samba.musicxml
     ...

3. Prepare dataset (pairs + references combined):
   python -m training.prepare_dataset \
     --data-dir data/songs \
     --reference-dir data/references \
     --output data/training.jsonl

4. Inspect the JSONL — sanity check the intermediate representation

5. Fine-tune:
   python -m training.train \
     --dataset data/training.jsonl \
     --output models/bossa-lora

6. Package for Ollama:
   ollama create bossa-llama3 -f services/training/Modelfile

7. Update LLM_MODEL env var in the composer deployment to use bossa-llama3
```

## When to Fine-Tune vs. Improve Prompt

Fine-tuning is worth it when:
- You have 20+ high-quality curated examples
- Prompt-engineered output quality has plateaued
- The task requires consistent style that's hard to describe in a prompt

Start by collecting examples and improving the system prompt in `llm_client.py` first. Fine-tuning is a multiplier on a good foundation — not a substitute for one.
