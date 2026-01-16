import random
import re

# Набор “человеческих” реакций
DEFAULT_REACTIONS = ["😂", "🤣", "💀", "🤡", "😈", "😐", "🙃", "👍", "👀", "🤝", "🔥", "💩"]

def pick_reaction(text: str) -> str:
    t = (text or "").lower()

    # супер-простая эвристика “как человек”
    if any(w in t for w in ["ахаха", "лол", "ору", "смеш", "😂", "🤣"]):
        return random.choice(["😂", "🤣", "💀"])
    if any(w in t for w in ["бред", "чушь", "ерунда", "кринж", "стыд", "🤡"]):
        return random.choice(["🤡", "💀", "🙃"])
    if any(w in t for w in ["ок", "пон", "ладно", "ясно", "норм"]):
        return random.choice(["👍", "🤝", "👌", "🫡"])
    if any(w in t for w in ["что", "чего", "серьёзно", "реально", "wtf", "почему"]):
        return random.choice(["😐", "👀", "🙃"])
    if "@" in t:  # кто-то кого-то тегает — часто “глазки”
        return random.choice(["👀", "😈", "🤡"])
    if len(t) > 140:  # длинный текст — “я прочитал”
        return random.choice(["👀", "🫡", "🤝"])

    # дефолт
    return random.choice(DEFAULT_REACTIONS)

def should_react_only(is_mention: bool) -> bool:
    # Даже при упоминании — иногда просто реакция.
    base = 0.22 if is_mention else 0.14
    return random.random() < base

def should_react_alongside_text(is_mention: bool) -> bool:
    # Иногда реакция + текст (как “человек”)
    base = 0.28 if is_mention else 0.18
    return random.random() < base
