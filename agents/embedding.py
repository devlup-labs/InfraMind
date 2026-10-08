from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")


def generate_embeddings(logs: list[str]) -> list[list[float]]:
    embeddings = model.encode(logs)
    return embeddings.tolist()