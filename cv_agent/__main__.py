"""
cv_agent.__main__ — CLI entrypoint.

Usage:
    python -m cv_agent
    cv-agent          (when installed via pip)
"""

from __future__ import annotations

import sys
from argparse import ArgumentParser


def main(argv: list[str] | None = None) -> int:
    """Run a health check and print runtime status to stdout."""
    parser = ArgumentParser(prog="cv-agent", description="CV Engineering Agent health check")
    parser.parse_args(argv)
    from cv_agent.runtime.agent import CVAgent

    try:
        agent = CVAgent()
        health = agent.health_check()
    except Exception as exc:  # noqa: BLE001
        print(f"CV Engineering Agent — STARTUP FAILURE\n  {exc}", file=sys.stderr)
        return 2

    lg_label = (
        f"available (v{health['langgraph_version']})"
        if health["langgraph_available"]
        else "UNAVAILABLE"
    )

    print("CV Engineering Agent — Health Check")
    print(f"  Runtime status  : {health['status'].upper()}")
    print(f"  Provider        : {health['provider']}")
    print(f"  Model           : {health['model']}")
    print(f"  Capabilities    : {health['capability_count']} registered")
    print(f"  LangGraph       : {lg_label}")

    return 0 if health["status"] == "ok" else 1


if __name__ == "__main__":
    sys.exit(main())
