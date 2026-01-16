from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from .settings import settings

_client = None

def client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=settings.OPENAI_API_KEY)
    return _client

SYSTEM_PROMPT = """Ты — "Балбес": дерзкий, саркастичный, мемный чат-бот для закрытой компании друзей.
Правила:
- Можно: грубый юмор, подколы, сарказм, троллинг без травли.
- Нельзя: угрозы насилием, разжигание ненависти, унижения по защищённым признакам, призывы к реальному вреду.
- Отвечай на языке пользователя.
- Если тебя просят сделать явно вредное/опасное — откажись коротко и переведи в безопасный юмор.
"""

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=6))
def embed(text: str) -> list[float]:
    # text-embedding-3-small — норм для памяти/поиска
    rsp = client().embeddings.create(model="text-embedding-3-small", input=text)
    return rsp.data[0].embedding

@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
def chat(user_text: str, context_snippets: str) -> str:
    msgs = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": f"Контекст из истории чата (может быть неполный):\n{context_snippets}".strip()},
        {"role": "user", "content": user_text},
    ]
    rsp = client().chat.completions.create(
        model=settings.OPENAI_MODEL,
        messages=msgs,
        temperature=0.9,
        max_tokens=400,
    )
    return (rsp.choices[0].message.content or "").strip()
