from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Telegram / app ---
    BOT_TOKEN: str = ""
    TARGET_GROUP_ID: int = 0

    GIPHY_API_KEY: str = ""
    GIPHY_RATING: str = "r"
    GIPHY_LANG: str = "ru"
    GIPHY_PROB: float = 0.18

    # --- DB ---
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "balbes_db"
    DB_USER: str = "balbes"
    DB_PASSWORD: str = "balbes"

    # --- OpenAI ---
    OPENAI_API_KEY: str = ""
    OPENAI_TEXT_MODEL: str = "gpt-4o-mini"

    # --- Behavior ---
    SPONTANEOUS_PROB: float = 0.06
    SPONTANEOUS_MIN_SEC: int = 120
    SPONTANEOUS_MAX_SEC: int = 420

    # --- Owner / defense mode ---
    OWNER_USER_ID: int = 1434320989

    # как “называется” владелец в чатике (для формулировок)
    OWNER_ALIAS: str = "владелец"

    # слова/упоминания владельца (по ним включаем защиту)
    OWNER_HANDLES: list[str] = ["балбес", "balbes", "владелец", "автор"]

    # включатели защиты
    OWNER_DEFENSE_MODE: bool = True
    DEFEND_ON_MENTION: bool = True
    DEFEND_ON_REPLY_TO_OWNER: bool = True

    # в споре про владельца — всегда на его стороне
    ALWAYS_SIDE_WITH_OWNER: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
