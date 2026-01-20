from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Telegram
    BOT_TOKEN: str = ""
    TARGET_GROUP_ID: int = 0

    # Owner
    OWNER_USER_ID: int = 1434320989
    OWNER_ALIAS: str = "владелец"
    OWNER_HANDLES: list[str] = ["балбес", "balbes", "владелец", "автор"]

    OWNER_DEFENSE_MODE: bool = True
    DEFEND_ON_MENTION: bool = True
    DEFEND_ON_REPLY_TO_OWNER: bool = True

    USE_TELEGRAM_REPLY: bool = False

    # DB
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "balbes_db"
    DB_USER: str = "balbes"
    DB_PASSWORD: str = "balbes"

    # OpenAI (оставляем как запасной вариант, но можно не использовать)
    OPENAI_API_KEY: str = ""
    OPENAI_TEXT_MODEL: str = "gpt-4o-mini"
    OPENAI_MAX_TOKENS: int = 180

    # OpenRouter (основной провайдер)
    OPENROUTER_API_KEY: str = ""
    OPENROUTER_BASE_URL: str = "https://openrouter.ai/api/v1"
    OPENROUTER_APP_NAME: str = "ai-balbes-bot"
    OPENROUTER_SITE_URL: str = ""

    # модели
    OPENROUTER_TEXT_MODEL: str = "meta-llama/llama-3.1-70b-instruct"
    OPENROUTER_TEXT_FALLBACKS: str = "meta-llama/llama-3.1-8b-instruct,mistralai/mixtral-8x7b-instruct"

    # ВАЖНО: vision модель должна поддерживать картинки
    OPENROUTER_VISION_MODEL: str = "qwen/qwen2.5-vl-72b-instruct"
    OPENROUTER_VISION_FALLBACKS: str = "qwen/qwen2-vl-72b-instruct"

    # GIPHY
    GIPHY_API_KEY: str = ""
    GIPHY_RATING: str = "r"
    GIPHY_LANG: str = "ru"
    GIPHY_PROB: float = 0.22

    # Memory 24h
    MEMORY_24H_LIMIT: int = 70
    MEMORY_24H_MAX_CHARS: int = 6500

    # Reply behavior
    REPLY_TO_OWNER: bool = False          # владелец -> вообще не отвечать
    REPLY_PROB_NORMAL: float = 0.92       # почти всегда остальным
    REPLY_COOLDOWN_SEC: int = 8           # антиспам на чат
    REACT_PROB_WHEN_SILENT: float = 0.35  # если решили молчать — часто реакция

    # Spontaneous
    SPONTANEOUS_PROB: float = 0.12
    SPONTANEOUS_MIN_SEC: int = 180
    SPONTANEOUS_MAX_SEC: int = 540
    SPONTANEOUS_COOLDOWN_SEC: int = 3600
    SPONTANEOUS_ONLY_IF_SILENT_SEC: int = 600

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
