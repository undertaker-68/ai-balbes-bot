from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # --- Telegram / app ---
    BOT_TOKEN: str = ""
    TARGET_GROUP_ID: int = 0

    # --- GIPHY ---
    GIPHY_API_KEY: str = ""
    GIPHY_RATING: str = "r"
    GIPHY_LANG: str = "ru"
    GIPHY_PROB: float = 0.18

    # --- Reply/React gating ---
    REPLY_PROB_NORMAL: float = 0.08          # шанс ответить на обычный месседж
    REPLY_COOLDOWN_SEC: int = 25             # не чаще, чем раз в N секунд на чат
    REACT_PROB_WHEN_SILENT: float = 0.12     # шанс поставить реакцию, если решил молчать

    # При защите владельца/владельце — всегда отвечаем (обычно так и надо)
    ALWAYS_REPLY_OWNER: bool = True
    ALWAYS_REPLY_DEFEND_OWNER: bool = True

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
    OWNER_ALIAS: str = "владелец"
    OWNER_HANDLES: list[str] = ["балбес", "balbes", "владелец", "автор"]

    OWNER_DEFENSE_MODE: bool = True
    DEFEND_ON_MENTION: bool = True
    DEFEND_ON_REPLY_TO_OWNER: bool = True

    ALWAYS_SIDE_WITH_OWNER: bool = True

    class Config:
        env_file = ".env"
        extra = "ignore"


settings = Settings()
