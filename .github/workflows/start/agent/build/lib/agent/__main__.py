"""에이전트 진입점.

실행: python -m agent
로그는 stdout/stderr → systemd journal 로 전달 (journalctl -u osv-agent -f).
"""
from __future__ import annotations

import logging
import sys
import time

from .config import Config


def setup_logging(level: str) -> logging.Logger:
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stdout,
    )
    return logging.getLogger("osv-agent")


def collect_once(cfg: Config, log: logging.Logger) -> int:
    """OSV API 수집 1회 (스켈레톤). 실제 수집 로직은 추후 구현."""
    log.info("OSV 수집 시작 (timeout=%ss)", cfg.osv_api_timeout)
    # TODO: httpx 로 OSV API 호출 → T2 (cfg.t2_api_url) 로 결과 전송
    log.info("OSV 수집 완료, T2 보고 대상=%s", cfg.t2_api_url)
    return 0


def main() -> int:
    cfg = Config.from_env()
    log = setup_logging(cfg.log_level)
    log.info("osv-agent 기동 (interval=%ss)", cfg.collector_interval)
    try:
        while True:
            collect_once(cfg, log)
            time.sleep(cfg.collector_interval)
    except KeyboardInterrupt:
        log.info("종료 신호 수신, 정상 종료")
        return 0
    except Exception:  # noqa: BLE001 - 최상위에서 fail 을 로그로 남기고 비정상 종료
        log.exception("수집 중 오류 발생")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
