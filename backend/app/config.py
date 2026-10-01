"""Settings from the environment, prefix ``NEXSIFT_``.

What the operator changes at runtime (rules, targets, retention, sign-in) lives in the database, see
``services/settings_service.py``. Only what must be known before the first start is here.
"""

from __future__ import annotations

import os
import secrets
from functools import lru_cache
from pathlib import Path

from pydantic import PrivateAttr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXSIFT_",
        env_file=(PROJECT_DIR / ".env", BACKEND_DIR / ".env"),
        extra="ignore",
    )

    data_dir: Path = PROJECT_DIR / "data"
    #: Protects the server-side secrets (OIDC client secret, source tokens, push credentials).
    secret_key: str = ""
    session_days: int = 30
    argon2_time: int = 3
    argon2_memory_kib: int = 65536
    argon2_parallelism: int = 2
    cookie_secure: str = "auto"
    disable_background: bool = False
    frontend_dist: Path = PROJECT_DIR / "frontend" / "dist"
    #: Overrides the level set in the interface (quiet, normal, detailed, trace; or WARNING, INFO, DEBUG). Empty:
    #: the interface decides. The emergency exit for "the app does not even start".
    log_level: str = ""
    #: Where the interface is reached from outside, for the OIDC redirect and the setup hints. Empty: from the
    #: request.
    public_url: str = ""
    trusted_proxies: str = ""
    api_docs: bool = False

    # The doors. Inside the container these stay fixed; compose maps them to whatever the host wants.
    host: str = "0.0.0.0"
    web_port: int = 8000
    #: Answers like a Gotify server (POST /message?token=…). 0 turns the door off.
    gotify_port: int = 8001
    #: Answers like an ntfy server (POST /<topic>). 0 turns the door off.
    ntfy_port: int = 8002
    #: Plain SMTP without sign-in, for devices that only send email. 0 turns it off.
    smtp_port: int = 2525
    #: Syslog over UDP and TCP. 0 turns it off.
    syslog_port: int = 5514
    #: What the setup hints show as ports, when compose maps the doors to other ones outside. Empty: the inner
    #: ones. Format: "web=8490,gotify=8491,ntfy=8492,smtp=25,syslog=514".
    public_ports: str = ""

    _remembered_key: str | None = PrivateAttr(default=None)

    @field_validator("data_dir", "frontend_dist")
    @classmethod
    def _relative_to_project(cls, value: Path) -> Path:
        return value if value.is_absolute() else PROJECT_DIR / value

    @property
    def database_path(self) -> Path:
        return self.data_dir / "nexsift.db"

    def outside_ports(self) -> dict[str, int]:
        ports = {
            "web": self.web_port,
            "gotify": self.gotify_port,
            "ntfy": self.ntfy_port,
            "smtp": self.smtp_port,
            "syslog": self.syslog_port,
        }
        for entry in self.public_ports.split(","):
            name, _, value = entry.partition("=")
            if name.strip() in ports and value.strip().isdigit():
                ports[name.strip()] = int(value.strip())
        return ports

    def key_from_environment(self) -> bool:
        return bool(self.secret_key)

    def resolved_secret_key(self) -> str:
        if self.secret_key:
            return self.secret_key
        if self._remembered_key:
            return self._remembered_key
        self.data_dir.mkdir(parents=True, exist_ok=True)
        key_file = self.data_dir / "secret.key"
        if key_file.exists():
            self._remembered_key = key_file.read_text(encoding="utf-8").strip()
        else:
            self._remembered_key = secrets.token_urlsafe(48)
            key_file.write_text(self._remembered_key, encoding="utf-8")
        try:
            os.chmod(key_file, 0o600)
        except OSError:
            pass
        return self._remembered_key


@lru_cache
def get_settings() -> Settings:
    return Settings()
