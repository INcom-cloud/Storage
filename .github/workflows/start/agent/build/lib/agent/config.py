"""환경변수 기반 설정 (systemd EnvironmentFile = /etc/osv-agent.env)."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    t2_api_url: str
    t2_api_key: str
    osv_api_timeout: int
    collector_interval: int
    log_level: str

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            t2_api_url=os.environ.get("T2_API_URL", "http://t2-api:8000"),
            t2_api_key=os.environ.get("T2_API_KEY", ""),
            osv_api_timeout=int(os.environ.get("OSV_API_TIMEOUT", "30")),
            collector_interval=int(os.environ.get("COLLECTOR_INTERVAL", "3600")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
        )
