from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    litellm_model: str = "anthropic/claude-sonnet-4-20250514"
    # 可用模型列表（供 MCP 等前端选择）
    available_models: str = (
        "anthropic/claude-sonnet-4-20250514,"
        "anthropic/claude-opus-4,"
        "openai/gpt-4o,"
        "openai/gpt-4o-mini,"
        "deepseek/deepseek-chat"
    )
    db_dir: str = ".orangeagent"
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

    model_config = {"env_prefix": "ORANGEAGENT_"}

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

    @property
    def model_list(self) -> list[str]:
        """可选的模型列表（解析自 available_models 逗号分隔）。"""
        return [m.strip() for m in self.available_models.split(",") if m.strip()]

    @property
    def provider_info(self) -> dict[str, bool]:
        """检查各 Provider 的 API key 是否已配置。"""
        import os
        return {
            "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
            "openai": bool(os.environ.get("OPENAI_API_KEY")),
            "deepseek": bool(os.environ.get("DEEPSEEK_API_KEY")),
        }


settings = Settings()
