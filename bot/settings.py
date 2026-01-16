from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    BOT_TOKEN: str
    OWNER_USER_ID: int
    TARGET_GROUP_ID: int
    OWNER_ONLY_MODE: bool = True

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_TEXT_MODEL: str = "gpt-4o-mini"
    OPENAI_TTS_MODEL: str = "gpt-4o-mini-tts"
    OPENAI_IMAGE_MODEL: str = "gpt-image-1"

    # Postgres
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "balbes_db"
    DB_USER: str = "balbes"
    DB_PASSWORD: str = "balbes_password"

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "tg_messages"

    # Autonomy
    AUTONOMY_ENABLED: bool = True
    REPLY_PROB: float = 0.35
    MENTION_REPLY_PROB: float = 0.70
    SPONTANEOUS_MIN_SEC: int = 300
    SPONTANEOUS_MAX_SEC: int = 1200
    SPONTANEOUS_PROB: float = 0.20

    # Media
    TENOR_API_KEY: str = ""
    ASSETS_DIR: str = "/app/assets"

    @property
    def db_dsn(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

settings = Settings()
