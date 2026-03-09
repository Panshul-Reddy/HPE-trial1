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


def _random_string(min_len: int = 5, max_len: int = 200) -> str:
    """Generate a random string of variable length for payload diversity."""
    words = [
        "hello", "world", "network", "traffic", "classify", "model",
        "protocol", "server", "client", "packet", "feature", "extract",
        "pipeline", "data", "stream", "connection", "session", "request",
        "response", "analysis", "machine", "learning", "neural", "deep",
        "transform", "encode", "decode", "binary", "metadata", "flow",
    ]
    result = []
    while len(" ".join(result)) < min_len:
        result.append(random.choice(words))
    text = " ".join(result)
    return text[:max_len]


def _random_echo_call() -> tuple[str, dict[str, Any]]:
    tool = random.choice(["echo", "echo_upper", "echo_reversed"])
    # Mix short and long messages for payload size variation
    if random.random() < 0.3:
        # Short message
        message = _random_string(3, 20)
    elif random.random() < 0.7:
        # Medium message
        message = _random_string(20, 100)
    else:
        # Long message
        message = _random_string(100, 500)
    return tool, {"message": message}


def _random_weather_call() -> tuple[str, dict[str, Any]]:
    tool = random.choice(["get_weather", "get_forecast"])
    city = random.choice([
        "New York", "London", "Tokyo", "Sydney", "Paris",
        "Berlin", "Mumbai", "São Paulo", "Toronto", "Seoul",
        "Cairo", "Lagos", "Mexico City", "Bangkok", "Istanbul",
    ])
    if tool == "get_forecast":
        return tool, {"city": city, "days": random.randint(1, 10)}
    return tool, {"city": city}


def _random_string_call() -> tuple[str, dict[str, Any]]:
    tool = random.choice(
        ["count_words", "count_characters", "to_title_case", "replace_substring", "split_text"]
    )
    # Vary text length for payload diversity
    text = _random_string(10, random.choice([30, 80, 150, 300]))
    if tool in ("count_words", "count_characters", "to_title_case"):
        return tool, {"text": text}
    if tool == "replace_substring":
        old_word = random.choice(text.split()) if text.split() else "a"
        return tool, {"text": text, "old": old_word, "new": "replaced"}
    return tool, {"text": text, "delimiter": random.choice([" ", ",", "."])}


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

async def run_session(url: str, session_id: int, num_requests: int, ca_cert: str | None = None) -> None:
    """Open one MCP client session and make num_requests tool calls.

    To create more unique flows, each session opens multiple short-lived SSE
    connections, making a few requests per connection before reconnecting.

    ca_cert: path to a CA certificate file to trust (needed for self-signed TLS certs).
    """
    logger.info("Session %d: starting %d requests against %s", session_id, num_requests, url)
    sent = 0
    conn_id = 0

    # Build an httpx client that trusts our self-signed cert when ca_cert is given
    import httpx
    if ca_cert:
        def _client_factory(headers=None, timeout=None, auth=None):
            return httpx.AsyncClient(verify=ca_cert, headers=headers, timeout=timeout, auth=auth)
        factory = _client_factory
    else:
        factory = None  # use default

    while sent < num_requests:
        reqs_this_conn = min(random.randint(1, 12), num_requests - sent)
        try:
            sse_kwargs = dict(url=url)
            if factory:
                sse_kwargs["httpx_client_factory"] = factory
            async with sse_client(**sse_kwargs) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()

                    for req_idx in range(reqs_this_conn):
                        tool_name, kwargs = _random_tool_call()
                        try:
                            result = await session.call_tool(tool_name, kwargs)
                            logger.debug(
                                "Session %d conn %d req %d: %s(%s) -> %s",
                                session_id, conn_id, req_idx,
                                tool_name, kwargs, result,
                            )
                        except Exception as exc:
                            logger.warning(
                                "Session %d conn %d req %d: %s(%s) failed: %s",
                                session_id, conn_id, req_idx,
                                tool_name, kwargs, exc,
                            )
                        # Varied timing: bursty (fast) or relaxed (slow)
                        if random.random() < 0.3:
                            await asyncio.sleep(random.uniform(0.001, 0.02))   # burst
                        elif random.random() < 0.7:
                            await asyncio.sleep(random.uniform(0.02, 0.15))    # normal
                        else:
                            await asyncio.sleep(random.uniform(0.2, 1.0))      # idle gap

            sent += reqs_this_conn
            conn_id += 1
        except Exception as exc:
            logger.error("Session %d conn %d: connection error: %s", session_id, conn_id, exc)
            sent += reqs_this_conn  # avoid infinite loop
            conn_id += 1

    logger.info("Session %d: completed %d requests across %d connections", session_id, num_requests, conn_id)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def run_all_sessions(url: str, num_sessions: int, num_requests: int, ca_cert: str | None = None) -> None:
    """Run all sessions, interleaved for realism."""
    tasks = [
        asyncio.create_task(run_session(url, i, num_requests, ca_cert=ca_cert))
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
    parser.add_argument(
        "--cert",
        default=None,
        help="Path to CA certificate to trust for self-signed TLS (e.g. certs/server.crt)",
    )
    args = parser.parse_args()

    asyncio.run(run_all_sessions(args.url, args.sessions, args.requests, ca_cert=args.cert))


if __name__ == "__main__":
    main()
