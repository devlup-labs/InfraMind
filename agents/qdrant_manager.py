import os
import uuid

from dotenv import load_dotenv
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, VectorParams, PointStruct , Filter

from embedding import generate_embeddings

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))

QDRANT_URL = os.getenv("QDRANT_URL")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION")

client = QdrantClient(url=QDRANT_URL)


def create_collection():
    """
    Creates the Qdrant collection if it doesn't already exist.
    """

    collections = client.get_collections().collections
    existing = [c.name for c in collections]

    if COLLECTION_NAME not in existing:
        client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(
                size=384,          # all-MiniLM-L6-v2 embedding size
                distance=Distance.COSINE
            ),
        )
        print(f"Created collection: {COLLECTION_NAME}")
    else:
        print(f"Collection '{COLLECTION_NAME}' already exists.")


def store_logs(logs: list[str]):
    """
    Embeds logs and stores them in Qdrant.
    """

    embeddings = generate_embeddings(logs)

    points = []

    for log, vector in zip(logs, embeddings):
        points.append(
            PointStruct(
                id=str(uuid.uuid4()),
                vector=vector,
                payload={
                    "log": log
                }
            )
        )

    client.upsert(
        collection_name=COLLECTION_NAME,
        points=points,
        wait=True
    )

    print(f"Stored {len(points)} logs in Qdrant.")


def search_logs(query: str, limit: int = 5):
    """
    Searches Qdrant for logs similar to the query.
    """

    query_vector = generate_embeddings([query])[0]

    results = client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=limit,
    ).points

    return [point.payload["log"] for point in results]