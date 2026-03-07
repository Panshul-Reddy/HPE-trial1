"""
Traffic generation orchestrator.

Coordinates the full pipeline:
  1. Start packet capture (scapy sniffer) in the background
  2. Start the MCP server and run the MCP client to generate MCP traffic
  3. Start the non-MCP server and run HTTP / WebSocket / TCP traffic generators
  4. Stop capture and save labelled pcap files

All components run as subprocesses so they can be started/stopped cleanly.
Designed to be invoked from the project root.

Usage:
    sudo python -m traffic_capture.orchestrator
    sudo python -m traffic_capture.orchestrator --duration 60 --requests 100
"""

import argparse
import asyncio
import logging
import os
import platform
import signal
import subprocess
import sys
import time
from pathlib import Path

IS_WINDOWS = platform.system() == "Windows"

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Ports
MCP_PORT = 8000
HTTP_PORT = 5000
WS_PORT = 5001
TCP_PORT = 5002

DATA_DIR = "data/pcap"


def _python() -> str:
    return sys.executable


def _start(args: list[str], **kwargs) -> subprocess.Popen:
    logger.info("Starting: %s", " ".join(args))
    popen_kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if IS_WINDOWS:
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["preexec_fn"] = os.setsid
    popen_kwargs.update(kwargs)
    return subprocess.Popen(args, **popen_kwargs)


def _stop(proc: subprocess.Popen, name: str) -> None:
    if proc.poll() is None:
        logger.info("Stopping %s (pid %d)", name, proc.pid)
        try:
            if IS_WINDOWS:
                proc.terminate()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except (ProcessLookupError, OSError):
            pass
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                if IS_WINDOWS:
                    proc.kill()
                else:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
            except (ProcessLookupError, OSError):
                pass


def _wait_for_port(host: str, port: int, timeout: float = 15.0) -> bool:
    """Return True once a TCP connection to host:port succeeds."""
    import socket

    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.25)
    return False


# ---------------------------------------------------------------------------
# TCP echo server (minimal, for tcp_traffic generator)
# ---------------------------------------------------------------------------

async def _tcp_echo_handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    import struct

    try:
        while True:
            header = await asyncio.wait_for(reader.readexactly(5), timeout=5.0)
            msg_type, length = struct.unpack("!BI", header)
            payload = await reader.readexactly(length) if length else b""
            # Pong for ping; echo everything else
            resp_type = 0x04 if msg_type == 0x03 else msg_type
            writer.write(struct.pack("!BI", resp_type, len(payload)) + payload)
            await writer.drain()
    except (asyncio.IncompleteReadError, asyncio.TimeoutError, ConnectionResetError):
        pass
    finally:
        writer.close()


async def _run_tcp_echo_server(host: str, port: int) -> None:
    server = await asyncio.start_server(_tcp_echo_handler, host, port)
    async with server:
        await server.serve_forever()


def _start_tcp_echo_server(host: str = "0.0.0.0", port: int = TCP_PORT) -> subprocess.Popen:
    """Start the TCP echo server as a subprocess.

    Each message is framed as [type:1B][length:4B][payload].
    The server echoes the payload back, converting PING (0x03) → PONG (0x04).
    """
    code = "\n".join([
        "import asyncio, struct",
        "async def handle(r, w):",
        "    try:",
        "        while True:",
        "            hdr = await asyncio.wait_for(r.readexactly(5), 5)",
        "            msg_type, length = struct.unpack('!BI', hdr)",
        "            payload = await r.readexactly(length) if length else b''",
        "            resp_type = 0x04 if msg_type == 0x03 else msg_type",
        "            w.write(struct.pack('!BI', resp_type, len(payload)) + payload)",
        "            await w.drain()",
        "    except Exception:",
        "        w.close()",
        f"async def main():",
        f"    server = await asyncio.start_server(handle, {host!r}, {port})",
        "    async with server:",
        "        await server.serve_forever()",
        "asyncio.run(main())",
    ])
    popen_kwargs: dict = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
    }
    if IS_WINDOWS:
        popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        popen_kwargs["preexec_fn"] = os.setsid
    return subprocess.Popen([_python(), "-c", code], **popen_kwargs)


def _default_loopback_interface() -> str:
    """Return the platform-appropriate default loopback interface name."""
    system = platform.system()
    if system == "Windows":
        # Npcap loopback adapter name varies; scan for it
        try:
            from scapy.all import get_if_list, conf
            # Try to find interface with 'Loopback' in description
            for iface_id, iface_obj in conf.ifaces.items():
                desc = getattr(iface_obj, 'description', '') or ''
                name = getattr(iface_obj, 'name', '') or ''
                if 'loopback' in desc.lower() or 'loopback' in name.lower():
                    return iface_id
            # Fallback: check interface list for NPF_Loopback
            for iface in get_if_list():
                if 'loopback' in iface.lower():
                    return iface
        except Exception:
            pass
        return r"\Device\NPF_Loopback"  # last-resort default
    elif system == "Darwin":
        return "lo0"
    return "lo"


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def run_pipeline(
    duration: int = 60,
    num_requests: int = 50,
    mcp_sessions: int = 3,
    ws_sessions: int = 3,
    tcp_connections: int = 3,
    interface: str = "",
    output_dir: str = DATA_DIR,
    capture: bool = True,
) -> None:
    """
    Run the full traffic generation pipeline.

    Parameters
    ----------
    duration:        Total traffic generation duration in seconds
    num_requests:    Number of requests per generator
    mcp_sessions:    Number of concurrent MCP client sessions
    ws_sessions:     Number of concurrent WebSocket sessions
    tcp_connections:  Number of concurrent TCP connections
    interface:       Network interface for packet capture
    output_dir:      Directory to save pcap files
    capture:         Whether to run the packet capture step
    """
    if not interface:
        interface = _default_loopback_interface()
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    procs: dict[str, subprocess.Popen] = {}

    try:
        # ------------------------------------------------------------------ #
        # 1. Start servers
        # ------------------------------------------------------------------ #
        procs["mcp_server"] = _start(
            [_python(), "-m", "mcp_server.server", "--port", str(MCP_PORT)]
        )
        procs["non_mcp_server"] = _start(
            [
                _python(), "-m", "non_mcp_traffic.server",
                "--http-port", str(HTTP_PORT),
                "--ws-port", str(WS_PORT),
            ]
        )
        procs["tcp_echo"] = _start_tcp_echo_server(port=TCP_PORT)

        logger.info("Waiting for servers to start…")
        for name, port in [("MCP", MCP_PORT), ("HTTP", HTTP_PORT), ("TCP", TCP_PORT)]:
            ok = _wait_for_port("127.0.0.1", port, timeout=20)
            if not ok:
                logger.warning("%s server on port %d not ready after 20s", name, port)

        # ------------------------------------------------------------------ #
        # 2. Start packet capture
        # ------------------------------------------------------------------ #
        if capture:
            cap_cmd = [
                _python(), "-m", "traffic_capture.capture",
                "--interface", interface,
                "--ports-mcp", str(MCP_PORT),
                "--ports-non-mcp", str(HTTP_PORT), str(WS_PORT), str(TCP_PORT),
                "--duration", str(duration + 5),   # slightly longer to catch stragglers
                "--output-dir", output_dir,
            ]
            procs["capture"] = _start(cap_cmd)
            time.sleep(1)  # give sniffer a moment to start

        # ------------------------------------------------------------------ #
        # 3. Run traffic generators
        # ------------------------------------------------------------------ #
        logger.info("Generating traffic for %d seconds…", duration)
        gen_start = time.time()

        traffic_procs: list[subprocess.Popen] = []

        # MCP client
        traffic_procs.append(_start([
            _python(), "-m", "mcp_client.client",
            "--url", f"http://localhost:{MCP_PORT}/sse",
            "--sessions", str(mcp_sessions),
            "--requests", str(num_requests),
        ]))

        # HTTP traffic
        traffic_procs.append(_start([
            _python(), "-m", "non_mcp_traffic.http_traffic",
            "--url", f"http://localhost:{HTTP_PORT}",
            "--requests", str(num_requests),
        ]))

        # WebSocket traffic
        traffic_procs.append(_start([
            _python(), "-m", "non_mcp_traffic.websocket_traffic",
            "--url", f"ws://localhost:{WS_PORT}",
            "--sessions", str(ws_sessions),
            "--messages", str(num_requests),
        ]))

        # TCP traffic
        traffic_procs.append(_start([
            _python(), "-m", "non_mcp_traffic.tcp_traffic",
            "--host", "localhost",
            "--port", str(TCP_PORT),
            "--connections", str(tcp_connections),
            "--messages", str(num_requests // max(1, tcp_connections) + 1),
        ]))

        # Wait for traffic generators to finish (up to duration)
        deadline = gen_start + duration
        for proc in traffic_procs:
            remaining = max(0, deadline - time.time())
            try:
                proc.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                _stop(proc, "traffic generator")

        logger.info("Traffic generation complete.")

    finally:
        # ------------------------------------------------------------------ #
        # 4. Stop servers; let capture finish writing pcap files
        # ------------------------------------------------------------------ #

        # Wait for capture to finish naturally (it has its own duration timer)
        capture_proc = procs.pop("capture", None)
        if capture_proc is not None and capture_proc.poll() is None:
            logger.info("Waiting for capture process to finish and save pcap files…")
            try:
                capture_proc.wait(timeout=duration + 15)
            except subprocess.TimeoutExpired:
                logger.warning("Capture process did not finish in time, stopping it.")
                _stop(capture_proc, "capture")

        # Now stop all remaining servers
        for name, proc in procs.items():
            _stop(proc, name)

    logger.info("Pipeline finished. pcap files are in: %s", output_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description="Traffic Generation Orchestrator")
    parser.add_argument("--duration", type=int, default=60, help="Traffic duration in seconds")
    parser.add_argument("--requests", type=int, default=50, help="Requests per generator")
    parser.add_argument("--mcp-sessions", type=int, default=3, help="Concurrent MCP sessions")
    parser.add_argument("--ws-sessions", type=int, default=3, help="Concurrent WebSocket sessions")
    parser.add_argument("--tcp-connections", type=int, default=3, help="Concurrent TCP connections")
    parser.add_argument(
        "--interface", default="",
        help="Network interface for capture (default: auto-detect per platform)",
    )
    parser.add_argument("--output-dir", default=DATA_DIR, help="Directory for pcap files")
    parser.add_argument(
        "--no-capture", action="store_true", help="Skip packet capture (generate traffic only)"
    )
    args = parser.parse_args()

    run_pipeline(
        duration=args.duration,
        num_requests=args.requests,
        mcp_sessions=args.mcp_sessions,
        ws_sessions=args.ws_sessions,
        tcp_connections=args.tcp_connections,
        interface=args.interface,
        output_dir=args.output_dir,
        capture=not args.no_capture,
    )


if __name__ == "__main__":
    main()
