from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    litellm_model: str = "anthropic/claude-sonnet-4-20250514"
    db_dir: str = ".duckagent"
    verify_enabled: bool = True
    verify_max_retries: int = 3
    prompts_dir: str = "prompts"
    trace_code_file: str | None = None
    trace_rw_file: str | None = None
    trace_bl_file: str | None = None
    jadx_host: str = "127.0.0.1"
    jadx_port: int = 8650

    # Bus transport
    bus_transport: str = "local"  # "local" | "http"
    bus_server_host: str = "127.0.0.1"
    bus_server_port: int = 8720

    model_config = {"env_prefix": "DUCKAGENT_"}

    @property
    def db_path(self) -> Path:
        return Path(self.db_dir) / "messages.db"

    @property
    def prompts_path(self) -> Path:
        return Path(self.prompts_dir)

    @property
    def trace_files(self) -> dict[str, Path]:
        files = {}
        if self.trace_code_file:
            files["code"] = Path(self.trace_code_file)
        if self.trace_rw_file:
            files["rw"] = Path(self.trace_rw_file)
        if self.trace_bl_file:
            files["bl"] = Path(self.trace_bl_file)
        return files

    @property
    def bus_server_url(self) -> str:
        return f"http://{self.bus_server_host}:{self.bus_server_port}"

    @property
    def is_http_mode(self) -> bool:
        return self.bus_transport == "http"


settings = Settings()
