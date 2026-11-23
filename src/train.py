import argparse
from pathlib import Path
from .schema import LABELS
from .training_manifest import validate_training_manifest


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, default=Path("data/splits"))
    p.add_argument("--manifest", type=Path, required=True, help="Validated Phase 2L frozen split manifest")
    p.add_argument("--model", default="distilbert/distilbert-base-uncased")
    p.add_argument("--max-length", type=int, default=384)
    p.add_argument("--epochs", type=int, default=3)
    p.add_argument("--batch-size", type=int, default=2)
    args = p.parse_args()
    # All three splits and live eligibility evidence are validated BEFORE any ML
    # import or model loading. Train from those validated objects, never reread files.
    parts = validate_training_manifest(args.manifest, args.data)
    import numpy as np
    from datasets import Dataset, DatasetDict
    from sklearn.metrics import accuracy_score, precision_recall_fscore_support
    from transformers import (
        AutoModelForSequenceClassification, AutoTokenizer, DataCollatorWithPadding,
        Trainer, TrainingArguments,
    )
    raw = DatasetDict({name: Dataset.from_list(parts[name]) for name in ("train", "validation")})
    tokenizer = AutoTokenizer.from_pretrained(args.model, local_files_only=True)
    label2id = {v: i for i, v in enumerate(LABELS)}

    def preprocess(batch):
        subjects = [f"Topic: {a}\nRequirements: {b}" for a, b in zip(batch["topic"], batch["subject_spec"])]
        documents = [f"Title: {a}\nArticle: {b}" for a, b in zip(batch["article_title"], batch["article_text"])]
        tokens = tokenizer(subjects, documents, truncation=True, max_length=args.max_length)
        tokens["labels"] = [label2id[x] for x in batch["label"]]
        return tokens

    processed = raw.map(preprocess, batched=True, remove_columns=raw["train"].column_names)
    model = AutoModelForSequenceClassification.from_pretrained(
        args.model, num_labels=3, label2id=label2id, id2label={i: l for l, i in label2id.items()},
        local_files_only=True,
    )

    def metrics(pred):
        labels = pred.label_ids
        predictions = np.argmax(pred.predictions, axis=-1)
        precision, recall, f1, _ = precision_recall_fscore_support(
            labels, predictions, average="macro", zero_division=0
        )
        return {"accuracy": accuracy_score(labels, predictions),
                "macro_precision": precision, "macro_recall": recall, "macro_f1": f1}

    settings = TrainingArguments(
        output_dir="models/aic1-baseline", eval_strategy="epoch", save_strategy="epoch",
        load_best_model_at_end=True, metric_for_best_model="macro_f1", greater_is_better=True,
        per_device_train_batch_size=args.batch_size, per_device_eval_batch_size=args.batch_size,
        gradient_accumulation_steps=8, learning_rate=2e-5, num_train_epochs=args.epochs,
        weight_decay=0.01, save_total_limit=2, report_to="none", seed=42,
    )
    trainer = Trainer(
        model=model, args=settings, train_dataset=processed["train"],
        eval_dataset=processed["validation"], processing_class=tokenizer,
        data_collator=DataCollatorWithPadding(tokenizer), compute_metrics=metrics,
    )
    trainer.train()
    trainer.save_model("models/aic1-final")
    tokenizer.save_pretrained("models/aic1-final")
    print("Saved model to models/aic1-final; test split validated for integrity, excluded from training and model selection.")


if __name__ == "__main__":
    main()
