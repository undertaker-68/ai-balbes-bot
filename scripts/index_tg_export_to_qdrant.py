import os, json, time, re
from dotenv import load_dotenv
from openai import OpenAI
from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

load_dotenv()

OPENAI_API_KEY = os.environ["OPENAI_API_KEY"]
QDRANT_URL = os.environ.get("QDRANT_URL", "http://127.0.0.1:6333")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "tg_messages")

client = OpenAI(api_key=OPENAI_API_KEY)
qdrant = QdrantClient(url=QDRANT_URL)

def flatten_text(t):
    # Telegram export: text может быть строкой или списком кусочков/emoji/entities
    if isinstance(t, str):
        return t.strip()
    if isinstance(t, list):
        parts = []
        for x in t:
            if isinstance(x, str):
                parts.append(x)
            elif isinstance(x, dict):
                # бывает {"type":"text","text":"..."} или {"type":"custom_emoji","text":"..."}
                parts.append(x.get("text") or x.get("content") or "")
        return "".join(parts).strip()
    return ""

def ensure_collection():
    exists = qdrant.collection_exists(COLLECTION)
    if not exists:
        qdrant.create_collection(
            collection_name=COLLECTION,
            vectors_config=qm.VectorParams(size=1536, distance=qm.Distance.COSINE),
        )

def embed(text: str):
    # троттлинг: 1 запрос/сек, чтобы не ловить 429 на маленьких лимитах
    time.sleep(1.05)
    r = client.embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    return r.data[0].embedding

def main(path: str):
    ensure_collection()

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    msgs = data.get("messages", [])
    points = []
    upserted = 0

    for m in msgs:
        if m.get("type") != "message":
            continue

        text = flatten_text(m.get("text"))
        if not text:
            continue

        # можно ограничить слишком длинные
        text = text[:2000]

        msg_id = m.get("id")
        date = m.get("date")
        frm = m.get("from")
        frm_id = m.get("from_id")

        vec = embed(text)

        payload = {
            "msg_id": msg_id,
            "date": date,
            "from": frm,
            "from_id": frm_id,
            "text": text,
        }

        points.append(qm.PointStruct(id=int(msg_id), vector=vec, payload=payload))

        if len(points) >= 64:
            qdrant.upsert(collection_name=COLLECTION, points=points)
            upserted += len(points)
            points = []
            print("upserted:", upserted)

    if points:
        qdrant.upsert(collection_name=COLLECTION, points=points)
        upserted += len(points)
        print("upserted:", upserted)

    print("DONE. total:", upserted)

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python scripts/index_tg_export_to_qdrant.py /root/tg_export/result.json")
        raise SystemExit(2)
    main(sys.argv[1])
