import random

# Набор “человеческих” реакций
DEFAULT_REACTIONS = ["😂", "🤣", "💀", "🤡", "😈", "😐", "🙃", "👍", "👀", "🤝", "🔥", "💩"]

def pick_reaction(text: str) -> str:
    t = (text or "").lower()

    # смех
    if any(w in t for w in ["ахаха", "лол", "ору", "смеш", "😂", "🤣", "хаха"]):
        return random.choice(["😂", "🤣", "💀"])

    # кринж / хрень
    if any(w in t for w in ["бред", "чушь", "ерунда", "кринж", "стыд", "🤡", "пиздец"]):
        return random.choice(["🤡", "💀", "🙃"])

    # согласие / подтверждение
    if any(w in t for w in ["ок", "пон", "ладно", "ясно", "норм", "база"]):
        return random.choice(["👍", "🤝", "👌", "🫡", "🔥"])

    # вопросы / недоумение
    if any(w in t for w in ["что", "чего", "серьёзно", "реально", "wtf", "почему"]):
        return random.choice(["😐", "👀", "🙃"])

    # теги
    if "@" in t:
        return random.choice(["👀", "😈", "🤡"])

    # длинный текст — “прочитал”
    if len(t) > 140:
        return random.choice(["👀", "🫡", "🤝"])

    return random.choice(DEFAULT_REACTIONS)


def should_react_only(is_mention: bool, mode: str | None = None) -> bool:
    """
    Возвращает True, если бот должен ТОЛЬКО поставить реакцию и не писать текст.
    """
    if is_mention:
        return random.random() < 0.55  # при обращении часто просто реакция

    if mode in ("owner", "defend_owner"):
        return random.random() < 0.25  # иногда поддакнуть реакцией

    return random.random() < 0.15


def should_react_alongside_text(is_mention: bool, mode: str | None = None) -> bool:
    """
    Реакция + текст (как живой человек).
    """
    if is_mention:
        return random.random() < 0.45

    if mode in ("owner", "defend_owner"):
        return random.random() < 0.35

    return random.random() < 0.18
