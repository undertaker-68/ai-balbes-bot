import orjson
from dataclasses import dataclass

@dataclass
class ExportedMsg:
    chat_title: str | None
    user_id: int | None
    username: str | None
    text: str
    created_at: str | None

def _text_field_to_str(text_field) -> str:
    # Telegram export JSON: text может быть string или массивом частей
    if isinstance(text_field, str):
        return text_field
    if isinstance(text_field, list):
        parts = []
        for p in text_field:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict) and "text" in p:
                parts.append(str(p["text"]))
        return "".join(parts)
    return ""

def parse_tg_export_json(path: str) -> list[ExportedMsg]:
    raw = open(path, "rb").read()
    data = orjson.loads(raw)

    chat_title = data.get("name")
    messages = data.get("messages", [])
    out: list[ExportedMsg] = []

    for m in messages:
        if m.get("type") != "message":
            continue
        text = _text_field_to_str(m.get("text", ""))
        text = (text or "").strip()
        if not text:
            continue

        # from_id часто "user123456", либо None
        uid = None
        from_id = m.get("from_id")
        if isinstance(from_id, str) and from_id.startswith("user"):
            try:
                uid = int(from_id.replace("user", ""))
            except Exception:
                uid = None

        out.append(ExportedMsg(
            chat_title=chat_title,
            user_id=uid,
            username=m.get("from"),
            text=text,
            created_at=m.get("date"),
        ))

    return out
