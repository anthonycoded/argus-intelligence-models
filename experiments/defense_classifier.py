
import json
from pathlib import Path

import joblib
import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "aic1_synthetic_v2"
MODEL_DIR = ROOT / "experiments" / "models"
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# 1. Load the dataset
with (DATA / "aic1_synthetic_v2.jsonl").open(
    encoding="utf-8"
) as f:
    records = [json.loads(line) for line in f if line.strip()]

with (DATA / "group_splits.jsonl").open(
    encoding="utf-8"
) as f:
    splits = {
        row["group_id"]: row["split"]
        for row in map(json.loads, f)
    }

label_map = {"nondefense": 0, "defense": 1}

def get_split(name):
    subset = [
        r for r in records
        if splits[r["group_id"]] == name
    ]
    texts = [r["text"] for r in subset]
    labels = np.array([
        label_map[r["fixture_target"]] for r in subset
    ])
    return texts, labels

train_texts, y_train = get_split("train")
val_texts, y_val = get_split("validation")
test_texts, y_test = get_split("test")

# 2. Load our pretrained embedding model
print("Loading MiniLM...")
encoder = SentenceTransformer(
    "sentence-transformers/all-MiniLM-L6-v2",
    device="cpu"
)

# 3. Convert text to embeddings
print("Generating embeddings...")
X_train = encoder.encode(
    train_texts, convert_to_numpy=True,
    normalize_embeddings=True
)
X_val = encoder.encode(
    val_texts, convert_to_numpy=True,
    normalize_embeddings=True
)
X_test = encoder.encode(
    test_texts, convert_to_numpy=True,
    normalize_embeddings=True
)

print("Embedding shape:", X_train.shape)

# 4. Train our classifier head
classifier = LogisticRegression(
    max_iter=1000,
    random_state=42
)
classifier.fit(X_train, y_train)

# 5. Evaluate on validation data
print("\nVALIDATION RESULTS")
print(classification_report(
    y_val, classifier.predict(X_val),
    target_names=["nondefense", "defense"],
    zero_division=0
))

# Keep the test partition unused until we've
# finished experimenting with model choices.

# 6. Save the trained classification head
joblib.dump(
    classifier,
    MODEL_DIR / "defense_head.joblib"
)

# 7. Interactive testing
print("\nAIC-1 ready. Type an article or 'quit'.")

while True:
    article = input("\nArticle: ").strip()

    if article.lower() in {"quit", "exit"}:
        break

    if not article:
        continue

    embedding = encoder.encode(
        [article],
        normalize_embeddings=True
    )

    probability = classifier.predict_proba(embedding)[0, 1]
    prediction = (
        "DEFENSE" if probability >= 0.5
        else "NON-DEFENSE"
    )

    print(f"Defense probability: {probability:.1%}")
    print(f"Prediction: {prediction}")

