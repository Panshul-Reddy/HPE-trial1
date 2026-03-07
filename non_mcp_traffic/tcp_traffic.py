"""
Raw TCP traffic generator.

Opens raw TCP connections to a configurable host/port and exchanges
simple text/binary messages, simulating a custom application protocol.

Usage:
    python -m non_mcp_traffic.tcp_traffic
    python -m non_mcp_traffic.tcp_traffic --host localhost --port 5002 --connections 5 --messages 10
"""

import argparse
import asyncio
import logging
import random
import struct

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Simple framing: 4-byte big-endian length prefix + payload
MSG_TYPE_TEXT = 0x01
MSG_TYPE_BINARY = 0x02
MSG_TYPE_PING = 0x03
MSG_TYPE_PONG = 0x04

SAMPLE_TEXTS = [
    b"hello",
    b"get status",
    b"ping server",
    b"list resources",
    b"submit job",
]


def _frame(msg_type: int, payload: bytes) -> bytes:
    """Encode a message with a simple header: [type:1][length:4][payload]."""
    return struct.pack("!BI", msg_type, len(payload)) + payload


def _random_message() -> bytes:
    choice = random.choice(["text", "text", "binary", "ping"])
    if choice == "text":
        return _frame(MSG_TYPE_TEXT, random.choice(SAMPLE_TEXTS))
    if choice == "binary":
        size = random.randint(8, 256)
        return _frame(MSG_TYPE_BINARY, bytes(random.getrandbits(8) for _ in range(size)))
    return _frame(MSG_TYPE_PING, b"")


async def _tcp_session(host: str, port: int, num_messages: int, session_id: int) -> None:
    logger.info("TCP session %d: connecting to %s:%d", session_id, host, port)
    # Use short-lived connections: a few messages per connection
    sent = 0
    conn_id = 0
    while sent < num_messages:
        msgs_this_conn = min(random.randint(1, 4), num_messages - sent)
        try:
            reader, writer = await asyncio.open_connection(host, port)
            for _ in range(msgs_this_conn):
                msg = _random_message()
                writer.write(msg)
                await writer.drain()

                try:
                    header = await asyncio.wait_for(reader.readexactly(5), timeout=2.0)
                    _, length = struct.unpack("!BI", header)
                    if length > 0:
                        await asyncio.wait_for(reader.readexactly(length), timeout=2.0)
                except (asyncio.TimeoutError, asyncio.IncompleteReadError):
                    pass

                await asyncio.sleep(random.uniform(0.01, 0.08))

            writer.close()
            await writer.wait_closed()
            sent += msgs_this_conn
            conn_id += 1
        except OSError as exc:
            logger.error("TCP session %d conn %d: failed: %s", session_id, conn_id, exc)
            sent += msgs_this_conn  # skip to avoid infinite loop
            conn_id += 1
    logger.info("TCP session %d: done (%d connections)", session_id, conn_id)


async def run_tcp_traffic(
    host: str, port: int, num_connections: int, num_messages: int
) -> None:
    tasks = [
        asyncio.create_task(_tcp_session(host, port, num_messages, i))
        for i in range(num_connections)
    ]
    await asyncio.gather(*tasks)


def main() -> None:
    parser = argparse.ArgumentParser(description="TCP Traffic Generator")
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=5002, help="TCP echo server port")
    parser.add_argument("--connections", type=int, default=3, help="Number of TCP connections")
    parser.add_argument("--messages", type=int, default=10, help="Messages per connection")
    args = parser.parse_args()

    asyncio.run(run_tcp_traffic(args.host, args.port, args.connections, args.messages))


if __name__ == "__main__":
    main()
