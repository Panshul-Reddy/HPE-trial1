"""
MCP Client that connects to the MCP server and generates realistic tool-call
traffic for use in traffic classification experiments.

Supports configurable number of sessions and requests so that enough traffic
volume is produced for pcap capture and feature extraction.

Usage:
    python -m mcp_client.client
    python -m mcp_client.client --url http://localhost:8000 --sessions 5 --requests 20
"""

import argparse
import asyncio
import logging
import random
from typing import Any

from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


# ---------------------------------------------------------------------------
# Tool call helpers – each returns (tool_name, kwargs)
# ---------------------------------------------------------------------------

def _random_calculator_call() -> tuple[str, dict[str, Any]]:
    tool = random.choice(["add", "subtract", "multiply", "divide", "power", "sqrt"])
    a = round(random.uniform(-100, 100), 2)
    b = round(random.uniform(0.1, 100), 2)
    if tool == "sqrt":
        return tool, {"x": abs(a)}
    if tool in ("add", "subtract", "multiply", "divide", "power"):
        return tool, {"a": a, "b": b}
    return tool, {"a": a, "b": b}


def _random_echo_call() -> tuple[str, dict[str, Any]]:
    tool = random.choice(["echo", "echo_upper", "echo_reversed"])
    messages = [
        "hello world",
        "MCP traffic classification",
        "test message",
        "the quick brown fox",
        "network metadata features",
    ]
    return tool, {"message": random.choice(messages)}


def _random_weather_call() -> tuple[str, dict[str, Any]]:
    tool = random.choice(["get_weather", "get_forecast"])
    city = random.choice(["New York", "London", "Tokyo", "Sydney", "Paris"])
    if tool == "get_forecast":
        return tool, {"city": city, "days": random.randint(1, 7)}
    return tool, {"city": city}


def _random_string_call() -> tuple[str, dict[str, Any]]:
    tool = random.choice(
        ["count_words", "count_characters", "to_title_case", "replace_substring", "split_text"]
    )
    texts = [
        "hello world from MCP",
        "network traffic classification project",
        "machine learning pipeline",
    ]
    text = random.choice(texts)
    if tool in ("count_words", "count_characters", "to_title_case"):
        return tool, {"text": text}
    if tool == "replace_substring":
        return tool, {"text": text, "old": "the", "new": "a"}
    return tool, {"text": text, "delimiter": " "}


def _random_tool_call() -> tuple[str, dict[str, Any]]:
    category = random.choice(["calculator", "echo", "weather", "string"])
    if category == "calculator":
        return _random_calculator_call()
    if category == "echo":
        return _random_echo_call()
    if category == "weather":
        return _random_weather_call()
    return _random_string_call()


# ---------------------------------------------------------------------------
# Session logic
# ---------------------------------------------------------------------------

async def run_session(url: str, session_id: int, num_requests: int) -> None:
    """Open one MCP client session and make num_requests tool calls."""
    logger.info("Session %d: connecting to %s", session_id, url)
    try:
        async with sse_client(url=url) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_result = await session.list_tools()
                tool_names = [t.name for t in tools_result.tools]
                logger.info(
                    "Session %d: server exposes %d tools: %s",
                    session_id,
                    len(tool_names),
                    tool_names,
                )

                for req_idx in range(num_requests):
                    tool_name, kwargs = _random_tool_call()
                    try:
                        result = await session.call_tool(tool_name, kwargs)
                        logger.debug(
                            "Session %d req %d: %s(%s) -> %s",
                            session_id,
                            req_idx,
                            tool_name,
                            kwargs,
                            result,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Session %d req %d: %s(%s) failed: %s",
                            session_id,
                            req_idx,
                            tool_name,
                            kwargs,
                            exc,
                        )
                    # Small random pause between requests to mimic real usage
                    await asyncio.sleep(random.uniform(0.05, 0.3))

        logger.info("Session %d: completed %d requests", session_id, num_requests)
    except Exception as exc:
        logger.error("Session %d: connection error: %s", session_id, exc)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_all_sessions(url: str, num_sessions: int, num_requests: int) -> None:
    """Run all sessions, interleaved for realism."""
    tasks = [
        asyncio.create_task(run_session(url, i, num_requests))
        for i in range(num_sessions)
    ]
    await asyncio.gather(*tasks)


def main() -> None:
    parser = argparse.ArgumentParser(description="MCP Traffic Client")
    parser.add_argument(
        "--url",
        default="http://localhost:8000/sse",
        help="SSE URL of the MCP server (default: http://localhost:8000/sse)",
    )
    parser.add_argument(
        "--sessions",
        type=int,
        default=3,
        help="Number of concurrent client sessions (default: 3)",
    )
    parser.add_argument(
        "--requests",
        type=int,
        default=10,
        help="Number of tool calls per session (default: 10)",
    )
    args = parser.parse_args()

    asyncio.run(run_all_sessions(args.url, args.sessions, args.requests))


if __name__ == "__main__":
    main()
