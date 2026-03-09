"""
Non-MCP traffic server.

Provides a simple HTTP REST API (Flask) and a WebSocket endpoint (via the
`websockets` library).  Both are run together so that the HTTP/WebSocket
traffic generators in this package have something to talk to.

Usage:
    python -m non_mcp_traffic.server
    python -m non_mcp_traffic.server --http-port 5000 --ws-port 5001
"""

import argparse
import asyncio
import json
import logging
import threading
import time
from typing import Any

from flask import Flask, jsonify, request

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# ---------------------------------------------------------------------------
# In-memory data store
# ---------------------------------------------------------------------------

_items: dict[int, dict[str, Any]] = {}
_next_id: int = 1
_lock = threading.Lock()


def _new_item(data: dict) -> dict:
    global _next_id
    with _lock:
        item = {"id": _next_id, "created_at": time.time(), **data}
        _items[_next_id] = item
        _next_id += 1
    return item


# ---------------------------------------------------------------------------
# Flask HTTP REST API
# ---------------------------------------------------------------------------

app = Flask(__name__)
app.logger.setLevel(logging.WARNING)  # suppress Flask request logs to keep output clean


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok", "timestamp": time.time()})


@app.route("/items", methods=["GET"])
def list_items():
    return jsonify(list(_items.values()))


@app.route("/items/<int:item_id>", methods=["GET"])
def get_item(item_id: int):
    item = _items.get(item_id)
    if item is None:
        return jsonify({"error": "not found"}), 404
    return jsonify(item)


@app.route("/items", methods=["POST"])
def create_item():
    data = request.get_json(silent=True) or {}
    item = _new_item(data)
    return jsonify(item), 201


@app.route("/items/<int:item_id>", methods=["PUT"])
def update_item(item_id: int):
    data = request.get_json(silent=True) or {}
    with _lock:
        if item_id not in _items:
            return jsonify({"error": "not found"}), 404
        _items[item_id].update(data)
        item = _items[item_id]
    return jsonify(item)


@app.route("/items/<int:item_id>", methods=["DELETE"])
def delete_item(item_id: int):
    with _lock:
        item = _items.pop(item_id, None)
    if item is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({"deleted": item_id})


@app.route("/echo", methods=["POST"])
def http_echo():
    data = request.get_json(silent=True) or {}
    return jsonify(data)


def run_http_server(
    host: str = "0.0.0.0",
    port: int = 5000,
    certfile: str | None = None,
    keyfile: str | None = None,
) -> None:
    if certfile and keyfile:
        logger.info("Starting HTTPS server on %s:%d (TLS)", host, port)
        import ssl
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile, keyfile)
        app.run(host=host, port=port, threaded=True, use_reloader=False, ssl_context=ctx)
    else:
        logger.info("Starting HTTP server on %s:%d", host, port)
        app.run(host=host, port=port, threaded=True, use_reloader=False)


# ---------------------------------------------------------------------------
# WebSocket server (asyncio-based)
# ---------------------------------------------------------------------------

async def _ws_handler(websocket) -> None:
    """Handle a single WebSocket connection."""
    try:
        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                msg = {"type": "text", "data": raw}

            msg_type = msg.get("type", "echo")
            if msg_type == "ping":
                await websocket.send(json.dumps({"type": "pong"}))
            elif msg_type == "echo":
                await websocket.send(json.dumps({"type": "echo", "data": msg.get("data")}))
            elif msg_type == "time":
                await websocket.send(json.dumps({"type": "time", "value": time.time()}))
            else:
                await websocket.send(json.dumps({"type": "unknown", "received": msg}))
    except Exception:
        pass


def run_ws_server(host: str = "0.0.0.0", port: int = 5001) -> None:
    import websockets

    async def _serve() -> None:
        logger.info("Starting WebSocket server on %s:%d", host, port)
        async with websockets.serve(_ws_handler, host, port):
            await asyncio.Future()  # run forever

    asyncio.run(_serve())


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Non-MCP Traffic Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--http-port", type=int, default=5000)
    parser.add_argument("--ws-port", type=int, default=5001)
    parser.add_argument("--tls", action="store_true", help="Enable HTTPS using --cert and --key")
    parser.add_argument("--cert", default="certs/server.crt", help="Path to TLS certificate")
    parser.add_argument("--key", default="certs/server.key", help="Path to TLS private key")
    args = parser.parse_args()

    ws_thread = threading.Thread(
        target=run_ws_server, args=(args.host, args.ws_port), daemon=True
    )
    ws_thread.start()

    if args.tls:
        run_http_server(args.host, args.http_port, certfile=args.cert, keyfile=args.key)
    else:
        run_http_server(args.host, args.http_port)


if __name__ == "__main__":
    main()
