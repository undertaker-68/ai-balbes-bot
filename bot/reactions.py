import random

DEFAULT_REACTIONS = ["😂", "💀", "🤡", "😐", "👍", "👀", "🔥", "🤝"]

def pick_reaction(text: str) -> str:
    t = (text or "").lower()

    if any(w in t for w in ["ахаха", "лол", "ору", "смеш", "😂", "🤣", "хаха"]):
        return random.choice(["😂", "💀"])
    if any(w in t for w in ["бред", "чушь", "ерунда", "кринж", "стыд", "🤡", "пиздец"]):
        return random.choice(["🤡", "💀"])
    if any(w in t for w in ["ок", "пон", "ладно", "ясно", "норм", "база"]):
        return random.choice(["👍", "🤝"])
    if any(w in t for w in ["что", "чего", "серьёзно", "реально", "wtf", "почему", "?"]):
        return random.choice(["😐", "👀"])

    return random.choice(DEFAULT_REACTIONS)

def should_react_only(is_mention: bool, mode: str | None = None) -> bool:
    # ВАЖНО: если бота позвали — всегда текст, не только реакция
    if is_mention:
        return False
    if mode in ("owner", "defend_owner"):
        return random.random() < 0.08
    return random.random() < 0.05

def should_react_alongside_text(is_mention: bool, mode: str | None = None) -> bool:
    if is_mention:
        return random.random() < 0.10
    if mode in ("owner", "defend_owner"):
        return random.random() < 0.08
    return random.random() < 0.05
