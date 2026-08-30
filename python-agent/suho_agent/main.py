"""Python agent entry point — reads task from Rust CLI via stdin JSON, runs agent, writes events to stdout."""

from __future__ import annotations

import asyncio
import logging
import signal
import sys

import structlog

from suho_agent.config import AgentConfig
from suho_agent.ipc.bridge import IPCBridge
from suho_agent.agent.runtime import AgentRuntime


def configure_logging(level_name: str) -> None:
    """Configure structlog and standard logging to output ONLY to sys.stderr."""
    level = getattr(logging, level_name.upper(), logging.INFO)

    # Direct standard logging to sys.stderr
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=level)

    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.KeyValueRenderer(key_order=["event", "version"]),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
    )


async def async_main() -> None:
    """Main async entry point."""
    config = AgentConfig.load()
    configure_logging(config.logging.level)

    log = structlog.get_logger(__name__)
    log.info("SUHO Agent starting", version="0.1.0")

    bridge = IPCBridge(sys.stdin, sys.stdout)
    runtime = AgentRuntime(config=config, bridge=bridge)

    # Handle SIGTERM on supported platforms (POSIX only)
    if sys.platform != "win32":
        try:
            loop = asyncio.get_running_loop()
            loop.add_signal_handler(signal.SIGTERM, lambda: runtime.request_shutdown())
        except (NotImplementedError, AttributeError):
            pass

    await runtime.run()

    log.info("SUHO Agent exited cleanly")


def main() -> None:
    """CLI entry point."""
    try:
        asyncio.run(async_main())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
