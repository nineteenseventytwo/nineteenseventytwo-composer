# Study Plan: LLMs, Agentic Systems, and This Codebase

You've built something genuinely interesting for a first LLM project: a structured AI pipeline with a clean intermediate representation, graceful fallback, and a fine-tuning path. Here's how to build the mental model behind it.

---

## Stage 1: How LLMs Actually Work (2–3 hours)

You're using Llama 3 8B. Before going deeper, understand what it actually is.

### Watch / Read

**3Blue1Brown — "But what is a GPT?" (YouTube, 26 min)**
The best visual explanation of transformers. Covers tokens, attention, and how text prediction works. Nothing to install — just watch.

**Andrej Karpathy — "Intro to Large Language Models" (YouTube, 1 hour)**
Karpathy ran AI at Tesla and co-founded OpenAI. This talk is the most efficient overview of what LLMs are, what they can/can't do, and how to think about them as a tool. Watch at 1.25×. Download it before the flight.

**"The Illustrated Transformer" (jalammar.github.io)**
Visual walkthrough of the transformer architecture. Read after the videos for more depth.

### Key Concepts to Internalize

**Tokens ≠ words.** LLMs operate on tokens (~4 characters each). Your JSON intermediate representation is roughly 1000–3000 tokens per song. Llama 3.1 8B has a 128K token context window — though in practice you'll use ~5000–10000 tokens per request.

**Temperature controls randomness.** 0 = deterministic/repetitive, 1+ = creative/unreliable. The code uses 0.7, which may be too high for reliable structured JSON output — worth experimenting with 0.1–0.3.

**The model generates one token at a time**, sampling from a probability distribution over its vocabulary. It doesn't reason or plan — it predicts what token comes next given everything before it.

---

## Stage 2: Prompt Engineering (1–2 hours)

The system prompt in `services/composer/src/composer/llm_client.py` is your main lever before fine-tuning. Good prompts directly impact arrangement quality.

### Read

**Prompt Engineering Guide (promptingguide.ai)**
Free, comprehensive, practical. Read the Basics and Techniques sections. Skip model-specific sections.

### Key Techniques Relevant to Your Code

**Role prompting:** "You are an expert jazz arranger..." — already in your code. Good.

**Structured output instructions:** "Return ONLY valid JSON" — also in your code. Important.

**Few-shot examples:** Adding 1–2 concrete before/after transformation examples in the system prompt dramatically improves consistency. This is the fastest improvement you can make before fine-tuning.

**JSON mode:** Ollama supports `"format": "json"` in the request options, which constrains the model to only output valid JSON. Worth adding to `llm_client.py`.

### Things to Try

With the system running locally, experiment with:
1. Lowering temperature from 0.7 to 0.2 and comparing arrangement quality
2. Adding a concrete example input/output pair to the system prompt
3. Adding `"format": "json"` to the Ollama request options
4. Adding a validation + retry loop: if JSON is invalid, send it back with the parse error and ask for a correction (up to 3 attempts)

---

## Stage 3: Agentic Patterns (2 hours)

Your pipeline is a simple linear agent. Understanding the broader pattern space helps you extend it.

### Read

**"Building Effective Agents" — Anthropic (anthropic.com/research/building-effective-agents)**
The best practical guide to agentic system design. Short, opinionated, and directly applicable. Download the page as a PDF before flying.

**LangChain conceptual docs — "Agents" and "Tools" sections (python.langchain.com/docs/concepts)**
You don't need to use LangChain, but the vocabulary (tools, agents, memory, chains) is the shared language of this field.

### Patterns to Know

**Linear pipeline (what you have):** Input → Step 1 → Step 2 → Step 3 → Output. Simple, predictable, good for well-defined tasks.

**Tool use:** The LLM decides which functions to call. Your `musicxml-tools` library could be exposed as "tools" the LLM calls directly (e.g., `split_voices`, `generate_drums`). This is how ChatGPT plugins work.

**Reflection / self-correction:** After the LLM generates JSON, validate it and send it back with any errors, asking for a fix. More reliable than hoping for correct output on the first try. Directly applicable to `llm_client.py`.

**Multi-agent:** Multiple LLM calls in sequence, each with a different role. E.g., "melody arranger" → "harmony arranger" → "critic/reviewer". More complex, potentially higher quality.

### Most Impactful Near-Term Addition

Add a validation + retry loop in `LLMClient.transform_to_bossa()`. If the returned JSON doesn't parse or is missing `parts`/`metadata`, send it back with the error and ask for a correction (max 3 retries). This alone meaningfully improves reliability without any other changes.

---

## Stage 4: Fine-Tuning (3–4 hours, hands-on when GPU is ready)

Your `training/` service is ready to run. You just need data and GPU time.

### Read

**"Fine-Tuning LLMs: A Practical Guide" — Weights & Biases**
(wandb.ai/site/articles/fine-tuning-large-language-models)
Good overview of when to fine-tune vs. prompt engineer.

**Hugging Face PEFT docs (huggingface.co/docs/peft)**
The `peft` library is what `train.py` uses for LoRA. Read "Quickstart" and "LoRA".

**QLoRA paper abstract only** (arxiv.org/abs/2305.14314)
Just the abstract and introduction — gives you the mental model for what `BitsAndBytesConfig` in `train.py` is doing.

### When to Fine-Tune vs. Improve the Prompt

Fine-tuning makes sense when:
- You have 20+ high-quality curated examples
- Prompt-engineered output quality has plateaued
- The style is difficult to describe in words but easy to demonstrate with examples

Start by collecting 5–10 input/output MusicXML pairs first. Run `prepare_dataset.py` and inspect the JSONL output — make sure the intermediate representation looks musically correct before spending GPU time.

### Practical First Steps

1. Find 5 public domain songs with both a plain piano score and a known bossa arrangement
2. Run `prepare_dataset.py` and inspect the JSONL
3. Run one training epoch as a smoke test
4. Compare outputs: `ollama run llama3:8b` vs `ollama run bossa-llama3`

---

## Stage 5: Kubernetes and the GPU Stack (1 hour, when node is running)

### Things to Check Once the Node is Up

```bash
# GPU visible to Kubernetes
kubectl describe node 1972-home | grep -A5 "Capacity"
# Expect: nvidia.com/gpu: 1

# Ollama using GPU not CPU
kubectl logs -l app=llm-server | grep -i gpu

# VRAM usage during a request
ssh mchellmer@<tailscale-ip>
nvidia-smi   # run this while sending a request to see it spike
```

### Read

**Kubernetes docs — "Schedule GPUs"** (kubernetes.io/docs/tasks/manage-gpus)
How the NVIDIA device plugin exposes `nvidia.com/gpu` as a resource. Your `setup-gpu-node.yaml` installs this.

**Ollama docs — "GPU" section** (ollama.ai/docs)
Environment variables for controlling VRAM usage and GPU layers.

---

## Key Concepts Glossary

| Term | What It Means in This Codebase |
|---|---|
| **Token** | Smallest unit of LLM input/output (~4 chars). Your JSON IR is ~1000–3000 tokens |
| **Context window** | Max tokens the model sees at once — 128K for Llama 3.1 8B |
| **Temperature** | Output randomness. 0 = deterministic, 1+ = creative/unreliable |
| **Quantization** | Compressing model weights (float32 → int4) to fit in consumer VRAM |
| **LoRA** | Fine-tuning via small trainable adapter matrices on a frozen base model |
| **QLoRA** | LoRA on a 4-bit quantized base model — enables fine-tuning in 8GB VRAM |
| **Ollama** | Local LLM server — like Docker, but for models |
| **Intermediate representation (IR)** | The compact JSON format bridging music21 objects and the LLM |
| **System prompt** | Instructions prepended to every conversation — defines the model's role |
| **Agentic pipeline** | A sequence of steps where one or more involve LLM calls |

---

## Offline Reading Order (Plane)

1. [docs/architecture.md](architecture.md) — this codebase (20 min)
2. [docs/services/](services/) — all four service docs (30 min)
3. Karpathy "Intro to LLMs" — download beforehand (1 hour)
4. Anthropic "Building Effective Agents" — download as PDF (20 min)
5. Prompt Engineering Guide basics section (30 min, browser works offline if cached)
6. Re-read `services/composer/src/composer/llm_client.py` with new context
7. Re-read `services/training/src/training/train.py` with LoRA/QLoRA in mind
