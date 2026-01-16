import asyncio
import sys
from sqlalchemy import text as sql_text
from qdrant_client.http import models as qm

from bot.settings import settings
from bot.db import SessionLocal, engine
from bot.models import Base, MessageRow
from bot.tg_export_import import parse_tg_export_json
from bot.ai import embed
from bot.rag import qdrant_client, ensure_collection, upsert_points
from bot.utils import clamp_text

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.execute(sql_text("CREATE INDEX IF NOT EXISTS idx_messages_chat_id ON messages(chat_id);"))

async def main(export_path: str):
    await init_db()

    msgs = parse_tg_export_json(export_path)
    if not msgs:
        print("Нет сообщений для импорта.")
        return

    qc = qdrant_client()

    # узнаем размер эмбеддинга один раз
    test_vec = embed("ping")
    await ensure_collection(qc, vector_size=len(test_vec))

    points: list[qm.PointStruct] = []
    inserted = 0

    async with SessionLocal() as session:
        for i, m in enumerate(msgs, start=1):
            row = MessageRow(
                chat_id=settings.TARGET_GROUP_ID,  # привязываем к целевой группе
                user_id=m.user_id or 0,
                username=m.username,
                text=clamp_text(m.text, 8000),
            )
            session.add(row)
            await session.flush()  # получаем row.id

            vec = embed(row.text)
            points.append(qm.PointStruct(
                id=row.id,
                vector=vec,
                payload={
                    "text": row.text,
                    "user_id": row.user_id,
                    "username": row.username,
                    "created_at": m.created_at,
                }
            ))

            inserted += 1
            if len(points) >= 64:
                upsert_points(qc, points)
                points = []

            if i % 500 == 0:
                print(f"Импортировано: {i}")

        await session.commit()

    if points:
        upsert_points(qc, points)

    print(f"✅ Готово. Сообщений импортировано: {inserted}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python scripts/import_tg_export.py /path/to/result.json")
        raise SystemExit(1)
    asyncio.run(main(sys.argv[1]))
