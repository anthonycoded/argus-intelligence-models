
from sentence_transformers import SentenceTransformer
import numpy as np

MODEL = "sentence-transformers/all-MiniLM-L6-v2"

topic = (
    "Chinese armed forces conducting military operations, "
    "naval deployments, exercises, or blockade preparations "
    "near Taiwan and the Taiwan Strait."
)

articles = [
    "Chinese naval forces conduct military exercises near Taiwan.",
    "China increases naval deployments near Japan's southern islands.",
    "US military increases power projection in the western Pacific.",
    "Japanese government debates nuclear-powered submarines.",
    "India orders new naval corvettes.",
]

model = SentenceTransformer(MODEL, device="cpu")

embeddings = model.encode(
    [topic] + articles,
    normalize_embeddings=True,
    convert_to_numpy=True,
    show_progress_bar=False,
)

topic_vector = embeddings[0]
article_vectors = embeddings[1:]

# Normalized vector dot product equals cosine similarity.
scores = article_vectors @ topic_vector

ranking = np.argsort(-scores)

print("\nAIC-1 Semantic Candidate Ranking\n")

for position, index in enumerate(ranking, start=1):
    print(
        f"{position}. {scores[index]:.4f} "
        f"| {articles[index]}"
    )

