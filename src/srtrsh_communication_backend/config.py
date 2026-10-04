import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    DATABASE_URL: str = os.getenv(
        "SRTRSH_DATABASE_URL",
        os.getenv("DATABASE_URL", "postgres://srtrsh:srtrsh_dev@localhost:5433/srtrsh"),
    )
    PROMPT_ENGINE_URL: str = os.getenv("PROMPT_ENGINE_URL", "http://localhost:8000")
    PORT: int = int(os.getenv("PORT", "8002"))


settings = Settings()
