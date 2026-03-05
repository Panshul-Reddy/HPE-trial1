"""
WebSocket traffic generator.

Connects to the non-MCP WebSocket server and sends a realistic mix of
ping/pong, echo, and time-request messages.

Usage:
    python -m non_mcp_traffic.websocket_traffic
    python -m non_mcp_traffic.websocket_traffic --url ws://localhost:5001 --messages 30
"""

import argparse
import asyncio
import json
import logging
import random

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

ECHO_TEXTS = [
    "hello from the generator",
    "test payload",
    "network traffic classification",
    "websocket message",
    "MCP vs non-MCP",
]


async def run_ws_session(url: str, num_messages: int, session_id: int = 0) -> None:
    """Connect to the WS server and send num_messages messages."""
    import websockets

    logger.info("WS session %d: connecting to %s", session_id, url)
    try:
        async with websockets.connect(url, ping_interval=None) as ws:
            for _ in range(num_messages):
                msg_type = random.choice(["ping", "echo", "echo", "time"])
                if msg_type == "ping":
                    payload = json.dumps({"type": "ping"})
                elif msg_type == "echo":
                    payload = json.dumps({"type": "echo", "data": random.choice(ECHO_TEXTS)})
                else:
                    payload = json.dumps({"type": "time"})

                await ws.send(payload)
                try:
                    response = await asyncio.wait_for(ws.recv(), timeout=2.0)
                    logger.debug("WS session %d: recv %s", session_id, response)
                except asyncio.TimeoutError:
                    logger.debug("WS session %d: no response within timeout", session_id)

                await asyncio.sleep(random.uniform(0.05, 0.3))

        logger.info("WS session %d: completed %d messages", session_id, num_messages)
    except Exception as exc:
        logger.error("WS session %d: error: %s", session_id, exc)


async def run_ws_traffic(
    url: str, num_sessions: int, num_messages: int
) -> None:
    tasks = [
        asyncio.create_task(run_ws_session(url, num_messages, i))
        for i in range(num_sessions)
    ]
    await asyncio.gather(*tasks)


def main() -> None:
    parser = argparse.ArgumentParser(description="WebSocket Traffic Generator")
    parser.add_argument("--url", default="ws://localhost:5001", help="WebSocket server URL")
    parser.add_argument("--sessions", type=int, default=2, help="Number of WS sessions")
    parser.add_argument("--messages", type=int, default=20, help="Messages per session")
    args = parser.parse_args()

    asyncio.run(run_ws_traffic(args.url, args.sessions, args.messages))


if __name__ == "__main__":
    main()
