from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Telegram
    BOT_TOKEN: str

    # Access control
    OWNER_USER_ID: int
    TARGET_GROUP_ID: int
    OWNER_ONLY_MODE: bool = True

    # OpenAI
    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"

    # Postgres
    DB_HOST: str = "localhost"
    DB_PORT: int = 5432
    DB_NAME: str = "balbes_db"
    DB_USER: str = "balbes"
    DB_PASSWORD: str = "balbes_password"

    # Qdrant
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_COLLECTION: str = "tg_messages"

    # RAG
    RAG_TOP_K: int = 8
    RAG_MAX_CHARS: int = 5000

    @property
    def db_dsn(self) -> str:
        return f"postgresql+asyncpg://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

settings = Settings()
