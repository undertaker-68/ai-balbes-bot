from qdrant_client import QdrantClient
from qdrant_client.http import models as qm
from .settings import settings

def qc() -> QdrantClient:
    return QdrantClient(url=settings.QDRANT_URL)

def ensure_collection(vector_size: int) -> None:
    client = qc()
    names = [c.name for c in client.get_collections().collections]
    if settings.QDRANT_COLLECTION in names:
        return
    client.create_collection(
        collection_name=settings.QDRANT_COLLECTION,
        vectors_config=qm.VectorParams(size=vector_size, distance=qm.Distance.COSINE),
    )

def upsert(point_id: int, vector: list[float], payload: dict) -> None:
    client = qc()
    client.upsert(
        collection_name=settings.QDRANT_COLLECTION,
        points=[qm.PointStruct(id=point_id, vector=vector, payload=payload)],
    )

def search(query_vector: list[float], limit: int) -> list[dict]:
    client = qc()
    res = client.search(
        collection_name=settings.QDRANT_COLLECTION,
        query_vector=query_vector,
        limit=limit,
        with_payload=True,
    )
    out = []
    for r in res:
        p = r.payload or {}
        out.append({"score": r.score, "text": p.get("text",""), "username": p.get("username"), "user_id": p.get("user_id")})
    return out
