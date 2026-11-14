"""Validated, secret-free TOML configuration; paths are relative to config file."""

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sample_mode: bool = False
    profile: Literal["demo", "home", "corporate"] = "demo"
    runtime: str = "runtime"
    inbox: str = str(Path(__file__).parent / "demo/inbox")
    sent: str | None = None
    identity: list[str] = Field(default_factory=list)
    knowledge: str = str(Path(__file__).parent / "demo/kb")
    history_only: bool = True
    automatic_drafts: bool = True
    attachment_adapter: Literal["standard", "word_active"] = "standard"
    document_adapter: Literal["eml", "fake", "outlook_msg"] = "eml"
    document_timeout: int = Field(default=20, ge=1, le=300)
    stable_seconds: float = 0
    max_chars: int = Field(default=24000, ge=4000, le=1000000)
    lease_seconds: int = Field(default=90, ge=3, le=3600)
    retry_delay: int = Field(default=30, ge=1, le=3600)
    poll_seconds: int = Field(default=60, ge=1, le=86400)
    jira_servers: list[dict] = Field(default_factory=list)
    ai_backend: Literal["fake", "opencode"] = "fake"
    ai_input: Literal["argument", "stdin"] = "argument"
    ai_global_args: list[str] = Field(default_factory=list)
    ai_prefix: list[str] = Field(default_factory=list)
    ai_executable: str = "opencode"
    ai_agent: str = "plan"
    classify_model: str | None = None
    draft_model: str | None = None
    ai_timeout: int = Field(default=90, ge=1, le=3600)

    @model_validator(mode="after")
    def validate_servers(self):
        from urllib.parse import urlsplit

        seen = set()
        for server in self.jira_servers:
            allowed = {
                "server_id",
                "base_url",
                "token_env",
                "api_version",
                "timeout",
                "poll_seconds",
                "fixture",
                "closed_poll_seconds",
                "identity",
            }
            if set(server) - allowed:
                raise ValueError("알 수 없는 JIRA 설정")
            if not server.get("server_id") or server["server_id"] in seen:
                raise ValueError("JIRA server_id 중복/누락")
            seen.add(server["server_id"])
            url = urlsplit(server["base_url"])
            if (
                url.scheme != "https"
                or not url.hostname
                or url.username
                or url.password
                or url.query
                or url.fragment
            ):
                raise ValueError("JIRA base_url은 인증정보 없는 HTTPS URL이어야 합니다")
            if str(server.get("api_version", "2")) not in ("2", "3"):
                raise ValueError("지원하지 않는 API 버전")
            if server.get("timeout", 20) <= 0 or server.get("poll_seconds", 300) < 0:
                raise ValueError("JIRA timeout/주기 오류")
        if (
            self.profile == "corporate"
            and self.ai_backend == "fake"
            and not self.history_only
        ):
            raise ValueError("corporate fake backend는 이력 수집 모드에서만 허용됩니다")
        return self


def load(path=None):
    if not path:
        return Settings()
    p = Path(path).resolve()
    with p.open("rb") as f:
        data = tomllib.load(f)
    settings = Settings.model_validate(data)
    for key in ("runtime", "inbox", "sent", "knowledge"):
        value = getattr(settings, key)
        if value:
            setattr(settings, key, str((p.parent / value).resolve()))
    for server in settings.jira_servers:
        if server.get("fixture"):
            server["fixture"] = str((p.parent / server["fixture"]).resolve())
    return settings
