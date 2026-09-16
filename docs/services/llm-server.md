# Service: llm-server

**Role:** LLM inference server
**Software:** [Ollama](https://ollama.ai/)
**Hardware:** PC node, NVIDIA RTX 4060 (8GB VRAM)

## What It Does

Runs a quantized LLM (Llama 3 8B by default) and exposes it over HTTP on port 11434. Everything else in the stack treats it as a black-box service — send messages, get a response. No custom code in this service.

## Ollama Background

Ollama is a tool for running LLMs locally. It handles:
- Downloading and storing models (`ollama pull llama3:8b` — like `docker pull` but for models)
- Quantization — compressing model weights so they fit in consumer GPU VRAM
- Serving the model over a REST API compatible with OpenAI's chat format

**Quantization** is the key concept. A Llama 3 8B model at full `float32` precision needs ~32GB of VRAM. By quantizing weights to 4-bit integers (Q4_K_M format), it fits in ~5GB — well within 8GB. There is a small quality tradeoff, but for structured JSON-in/JSON-out transformation tasks it's negligible.

## The Modelfile

`services/training/Modelfile` defines a custom Ollama model derived from a base model. It sets a default system prompt used when no system message is provided. Once a LoRA adapter has been fine-tuned and merged into a model, the Modelfile packages it for deployment:

```bash
ollama create bossa-llama3 -f Modelfile
```

## API

The composer service calls Ollama's `/api/chat` endpoint:

```
POST http://llm-server:11434/api/chat
{
  "model": "llama3:8b",
  "messages": [
    {"role": "system", "content": "..."},
    {"role": "user",   "content": "..."}
  ],
  "stream": false
}
```

Response: `data["message"]["content"]` contains the model's reply text.

## VRAM Capacity Reference

| Model | Quantization | VRAM | Notes |
|---|---|---|---|
| Llama 3 8B | Q4_K_M | ~5 GB | Good quality, comfortable fit |
| Llama 3 8B | Q8_0 | ~8 GB | Better quality, tight fit |
| Mistral 7B | Q4_K_M | ~4.5 GB | Good alternative |
| Llama 3 13B | Q4_K_M | ~8 GB+ | Needs CPU offload on 8GB |

For the bossa transformation task (structured JSON in, JSON out), Q4_K_M 8B is a good balance. If output quality is poor, try Q8_0 before reaching for a larger model.

## Verifying GPU Usage

```bash
# On the GPU node
nvidia-smi                  # shows VRAM usage while a request is running
ollama ps                   # shows which models are loaded in VRAM

# In Kubernetes
kubectl describe node 1972-home | grep -A5 "Capacity"
# Should show: nvidia.com/gpu: 1
```
