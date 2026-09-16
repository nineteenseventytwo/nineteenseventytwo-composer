"""LoRA fine-tuning script for bossa arrangement model."""

import argparse
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def train(dataset_path: Path, output_dir: Path, base_model: str = "meta-llama/Meta-Llama-3.1-8B"):
    """Fine-tune a model on bossa arrangement examples using QLoRA.

    Args:
        dataset_path: Path to the JSONL training file.
        output_dir: Directory to save the fine-tuned adapter.
        base_model: HuggingFace model ID for the base model.
    """
    # Lazy imports — these are heavy dependencies
    from datasets import load_dataset
    from peft import LoraConfig, get_peft_model, prepare_model_for_kbit_training
    from transformers import (
        AutoModelForCausalLM,
        AutoTokenizer,
        BitsAndBytesConfig,
        TrainingArguments,
    )
    from trl import SFTTrainer

    logger.info("Loading dataset from %s", dataset_path)
    dataset = load_dataset("json", data_files=str(dataset_path), split="train")

    logger.info("Loading base model: %s", base_model)
    bnb_config = BitsAndBytesConfig(
        load_in_4bit=True,
        bnb_4bit_quant_type="nf4",
        bnb_4bit_use_double_quant=True,
    )

    tokenizer = AutoTokenizer.from_pretrained(base_model)
    tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        base_model,
        quantization_config=bnb_config,
        device_map="auto",
    )
    model = prepare_model_for_kbit_training(model)

    # LoRA config — target the attention layers
    lora_config = LoraConfig(
        r=16,
        lora_alpha=32,
        lora_dropout=0.05,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj"],
        task_type="CAUSAL_LM",
    )

    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # Format messages into a single string for training
    def format_messages(example):
        messages = example["messages"]
        text = ""
        for msg in messages:
            role = msg["role"]
            content = msg["content"]
            text += f"<|{role}|>\n{content}\n"
        text += "<|end|>"
        return {"text": text}

    dataset = dataset.map(format_messages)

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=3,
        per_device_train_batch_size=1,
        gradient_accumulation_steps=4,
        learning_rate=2e-4,
        warmup_steps=10,
        logging_steps=1,
        save_strategy="epoch",
        fp16=True,
    )

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=dataset,
        args=training_args,
        max_seq_length=8192,
    )

    logger.info("Starting training")
    trainer.train()

    logger.info("Saving adapter to %s", output_dir)
    model.save_pretrained(output_dir)
    tokenizer.save_pretrained(output_dir)

    logger.info("Training complete")


def main():
    parser = argparse.ArgumentParser(description="Fine-tune model for bossa arrangement")
    parser.add_argument("--dataset", type=Path, required=True, help="Path to training JSONL")
    parser.add_argument("--output", type=Path, default=Path("models/bossa-lora"))
    parser.add_argument("--base-model", default="meta-llama/Meta-Llama-3.1-8B")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    train(args.dataset, args.output, args.base_model)


if __name__ == "__main__":
    main()
