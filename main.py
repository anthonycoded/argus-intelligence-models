
import numpy as np
import torch

from datasets import load_dataset
from sklearn.metrics import (
    accuracy_score,
    precision_recall_fscore_support,
)
from transformers import (
    AutoModelForSequenceClassification,
    AutoTokenizer,
    DataCollatorWithPadding,
    Trainer,
    TrainingArguments,
)

MODEL_NAME = "distilbert/distilbert-base-uncased"

LABELS = {
    "unrelated": 0,
    "partially_relevant": 1,
    "relevant": 2,
}

raw = load_dataset(
    "json",
    data_files={
        "train": "data/splits/train.jsonl",
        "validation": "data/splits/validation.jsonl",
    },
)

tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

def preprocess(batch):
    encoded = tokenizer(
        batch["topic"],
        [
            title + " " + body
            for title, body in zip(
                batch["article_title"],
                batch["article_text"],
            )
        ],
        truncation=True,
        max_length=512,
    )
    encoded["labels"] = [
        LABELS[label] for label in batch["label"]
    ]
    return encoded

data = raw.map(
    preprocess,
    batched=True,
    remove_columns=raw["train"].column_names,
)

model = AutoModelForSequenceClassification.from_pretrained(
    MODEL_NAME,
    num_labels=3,
    id2label={v: k for k, v in LABELS.items()},
    label2id=LABELS,
)

def compute_metrics(prediction):
    predicted = np.argmax(prediction.predictions, axis=1)
    gold = prediction.label_ids

    precision, recall, f1, _ = (
        precision_recall_fscore_support(
            gold,
            predicted,
            average="macro",
            zero_division=0,
        )
    )

    return {
        "accuracy": accuracy_score(gold, predicted),
        "macro_precision": precision,
        "macro_recall": recall,
        "macro_f1": f1,
    }

args = TrainingArguments(
    output_dir="models/aic1-distilbert",
    eval_strategy="epoch",
    save_strategy="epoch",
    learning_rate=2e-5,
    per_device_train_batch_size=4,
    per_device_eval_batch_size=8,
    gradient_accumulation_steps=4,
    num_train_epochs=4,
    weight_decay=0.01,
    load_best_model_at_end=True,
    metric_for_best_model="macro_f1",
    greater_is_better=True,
    report_to="none",
    seed=42,
    fp16=False,
)

trainer = Trainer(
    model=model,
    args=args,
    train_dataset=data["train"],
    eval_dataset=data["validation"],
    processing_class=tokenizer,
    data_collator=DataCollatorWithPadding(tokenizer),
    compute_metrics=compute_metrics,
)

trainer.train()
trainer.save_model("models/aic1-final")
tokenizer.save_pretrained("models/aic1-final")
