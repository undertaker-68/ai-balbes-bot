import os
import json
import re
import asyncio
from datetime import datetime, timezone

import asyncpg
from dotenv import load_dotenv

load_dotenv()

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "balbes_db")
DB_USER = os.getenv("DB_USER", "balbes")
DB_PASSWORD = os.getenv("DB_PASSWORD", "balbes")

TARGET_CHAT_ID = int(os.getenv("TARGET_GROUP_ID", "0"))  # используем твой ID группы


def flatten_text(t):
    # Telegram export: text может быть строкой или списком (кусочки/emoji/entities)
    if isinstance(t, str):
        return t.strip()
    if isinstance(t, list):
        parts = []
        for x in t:
            if isinstance(x, str):
                parts.append(x)
            elif isinstance(x, dict):
                parts.append(x.get("text") or x.get("content") or "")
        return "".join(parts).strip()
    return ""


def parse_dt(s: str | None):
    if not s:
        return None
    # обычно формат "2026-01-16T..." или "2026-01-16 18:08:00"
    try:
        # поддержка ISO
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


async def main(path: str):
    conn = await asyncpg.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, database=DB_NAME
    )

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    msgs = data.get("messages", [])
    total = 0
    inserted = 0

    batch = []
    BATCH_SIZE = 500

    for m in msgs:
        if m.get("type") != "message":
            continue

        text = flatten_text(m.get("text"))
        if not text:
            continue

        msg_id = m.get("id")
        if msg_id is None:
            continue

        dt = parse_dt(m.get("date"))
        frm = m.get("from")
        frm_id = m.get("from_id")

        # чуть чистим мусор
        text = re.sub(r"\s+", " ", text).strip()

        batch.append((TARGET_CHAT_ID, int(msg_id), dt, frm, frm_id, text))
        total += 1

        if len(batch) >= BATCH_SIZE:
            res = await conn.executemany(
                """
                INSERT INTO tg_history (chat_id, msg_id, dt, from_name, from_id, text)
                VALUES ($1,$2,$3,$4,$5,$6)
                ON CONFLICT (chat_id, msg_id) DO NOTHING
                """,
                batch,
            )
            inserted += len(batch)
            print(f"loaded: {inserted}")
            batch = []

    if batch:
        await conn.executemany(
            """
            INSERT INTO tg_history (chat_id, msg_id, dt, from_name, from_id, text)
            VALUES ($1,$2,$3,$4,$5,$6)
            ON CONFLICT (chat_id, msg_id) DO NOTHING
            """,
            batch,
        )
        inserted += len(batch)

    await conn.close()
    print("DONE. messages:", total)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python scripts/import_tg_export_to_db.py /root/tg_export/result.json")
        raise SystemExit(2)

    asyncio.run(main(sys.argv[1]))
