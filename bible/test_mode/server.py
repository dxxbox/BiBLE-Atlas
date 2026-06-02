from __future__ import annotations

import argparse

import uvicorn

from bible.common.logger import get_logger
from bible.test_mode.app import create_app

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Start BiBLE Atlas Test Mode server.")
    parser.add_argument("--mode", default="server", choices=["server"])
    parser.add_argument("--addr", default="127.0.0.1:5555")
    parser.add_argument("--fixture", default=None, help="External fixture JSON file or directory containing JSON fixtures.")
    parser.add_argument("--strict", default="true", choices=["true", "false"])
    args = parser.parse_args()

    host, port = _parse_addr(args.addr)
    strict = args.strict == "true"
    logger.info(
        "Starting Test Mode server host=%s port=%s fixture=%s strict=%s",
        host,
        port,
        args.fixture or "<builtin-only>",
        strict,
    )
    app = create_app(fixture_path=args.fixture, strict=strict)
    uvicorn.run(app, host=host, port=port, log_config=None)


def _parse_addr(addr: str) -> tuple[str, int]:
    if ":" not in addr:
        return addr, 5555
    host, port_text = addr.rsplit(":", 1)
    return host, int(port_text)


if __name__ == "__main__":
    main()
