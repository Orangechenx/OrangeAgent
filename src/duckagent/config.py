from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings

load_dotenv()


class Settings(BaseSettings):
    litellm_model: str = "anthropic/claude-sonnet-4-20250514"
    db_dir: str = ".duckagent"
    verify_enabled: bool = True
    verify_max_retries: int = 3
    prompts_dir: str = "prompts"

    model_config = {"env_prefix": "DUCKAGENT_"}

    @property
    def db_path(self) -> Path:
        return Path(self.db_dir) / "messages.db"

    @property
    def prompts_path(self) -> Path:
        return Path(self.prompts_dir)


settings = Settings()
