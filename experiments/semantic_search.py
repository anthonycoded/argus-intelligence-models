
import json
from pathlib import Path

import numpy as np
from sentence_transformers import SentenceTransformer


ROOT = Path(__file__).resolve().parents[1]

DATASET = (
    ROOT
    / "aic1_synthetic_v2"
    / "aic1_synthetic_v2.jsonl"
)

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class SemanticSearch:

    def __init__(self):
        print("Loading embedding model...")

        self.model = SentenceTransformer(
            MODEL_NAME,
            device="cpu"
        )

        self.documents = []
        self.embeddings = None

    def load_documents(self, path):
        with open(path, "r", encoding="utf-8") as f:
            self.documents = [
                json.loads(line)
                for line in f
                if line.strip()
            ]

        print(f"Loaded {len(self.documents)} documents")

    def build_index(self):
        if not self.documents:
            raise ValueError("No documents loaded")

        texts = [
            doc["text"]
            for doc in self.documents
        ]

        print("Generating document embeddings...")

        self.embeddings = self.model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=True
        )

        print("Index shape:", self.embeddings.shape)

    def search(self, query, top_k=5):

        if self.embeddings is None:
            raise RuntimeError("Build index before searching")

        # Convert the query into a normalized embedding
        query_embedding = self.model.encode(
            [query],
            normalize_embeddings=True,
            convert_to_numpy=True
        )[0]

        # Dot product of normalized vectors = cosine similarity
        similarities = self.embeddings @ query_embedding

        # Find highest-scoring documents
        top_indices = np.argsort(-similarities)[:top_k]

        results = []

        for index in top_indices:
            doc = self.documents[int(index)]

            results.append({
                "id": doc["fixture_id"],
                "text": doc["text"],
                "label": doc["fixture_target"],
                "group_id": doc["group_id"],
                "similarity": float(similarities[index])
            })

        return results


def main():
    engine = SemanticSearch()

    engine.load_documents(DATASET)
    engine.build_index()

    print("\nAIC-1 Semantic Search Ready")
    print("Enter a query or type 'quit'")

    while True:
        query = input("\nSearch: ").strip()

        if query.lower() in {"quit", "exit"}:
            break

        if not query:
            continue

        results = engine.search(query)

        print("\nTOP MATCHES")

        for rank, result in enumerate(results, start=1):
            print(f"\n{rank}. {result['id']}")
            print(f"Similarity: {result['similarity']:.3f}")
            print(f"Label: {result['label']}")
            print(f"Group: {result['group_id']}")
            print(f"Text: {result['text']}")


if __name__ == "__main__":
    main()
