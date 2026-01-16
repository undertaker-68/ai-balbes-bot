from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from .settings import settings

def qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.QDRANT_URL)

async def ensure_collection(client: QdrantClient, vector_size: int) -> None:
    collections = client.get_collections().collections
    exists = any(c.name == settings.QDRANT_COLLECTION for c in collections)
    if exists:
        return
    client.create_collection(
        collection_name=settings.QDRANT_COLLECTION,
        vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
    )

def upsert_points(client: QdrantClient, points: list[qm.PointStruct]) -> None:
    client.upsert(collection_name=settings.QDRANT_COLLECTION, points=points)

def search(client: QdrantClient, query_vector: list[float], limit: int) -> list[dict]:
    res = client.search(
        collection_name=settings.QDRANT_COLLECTION,
        query_vector=query_vector,
        limit=limit,
        with_payload=True,
    )
    out = []
    for r in res:
        payload = r.payload or {}
        out.append({
            "score": r.score,
            "text": payload.get("text", ""),
            "user_id": payload.get("user_id"),
            "username": payload.get("username"),
            "created_at": payload.get("created_at"),
        })
    return out
