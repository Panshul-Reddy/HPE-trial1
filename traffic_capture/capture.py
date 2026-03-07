"""
Packet capture module.

Uses scapy to sniff packets on a network interface/port combination.
Packets are labelled as 'mcp' or 'non_mcp' based on which ports are
active during the capture window, then saved as a pcap file.

Usage (usually called from the orchestrator, but can be run standalone):
    sudo python -m traffic_capture.capture --interface lo --ports-mcp 8000 --duration 30
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def capture_traffic(
    interface: str,
    mcp_ports: list[int],
    non_mcp_ports: list[int],
    duration: int,
    output_dir: str = "data/pcap",
    label: Optional[str] = None,
) -> dict[str, str]:
    """
    Capture traffic on *interface* for *duration* seconds.

    Packets with src/dst port in mcp_ports are saved to an 'mcp' pcap file;
    packets with port in non_mcp_ports are saved to a 'non_mcp' pcap file.

    Returns a dict mapping label -> path for each saved pcap file.
    """
    try:
        from scapy.all import AsyncSniffer, wrpcap
    except ImportError as exc:
        raise ImportError("scapy is required for packet capture. Install it with: pip install scapy") from exc

    os.makedirs(output_dir, exist_ok=True)
    timestamp = int(time.time())

    all_ports = mcp_ports + non_mcp_ports
    bpf_filter = " or ".join(f"port {p}" for p in all_ports) if all_ports else ""

    logger.info(
        "Starting capture on %s for %ds (filter: %s)", interface, duration, bpf_filter or "none"
    )

    sniffer = AsyncSniffer(
        iface=interface,
        filter=bpf_filter or None,
        store=True,
    )
    sniffer.start()
    time.sleep(duration)
    sniffer.stop()
    packets = sniffer.results

    logger.info("Captured %d packets", len(packets))

    # Split by port
    from scapy.layers.inet import TCP, UDP

    mcp_pkts = []
    non_mcp_pkts = []

    for pkt in packets:
        if pkt.haslayer(TCP) or pkt.haslayer(UDP):
            layer = pkt[TCP] if pkt.haslayer(TCP) else pkt[UDP]
            sport, dport = layer.sport, layer.dport
            if sport in mcp_ports or dport in mcp_ports:
                mcp_pkts.append(pkt)
            elif sport in non_mcp_ports or dport in non_mcp_ports:
                non_mcp_pkts.append(pkt)

    saved: dict[str, str] = {}

    if mcp_pkts:
        suffix = f"_{label}" if label else ""
        path = str(Path(output_dir) / f"mcp{suffix}_{timestamp}.pcap")
        wrpcap(path, mcp_pkts)
        saved["mcp"] = path
        logger.info("Saved %d MCP packets to %s", len(mcp_pkts), path)

    if non_mcp_pkts:
        suffix = f"_{label}" if label else ""
        path = str(Path(output_dir) / f"non_mcp{suffix}_{timestamp}.pcap")
        wrpcap(path, non_mcp_pkts)
        saved["non_mcp"] = path
        logger.info("Saved %d non-MCP packets to %s", len(non_mcp_pkts), path)

    return saved


def main() -> None:
    parser = argparse.ArgumentParser(description="Packet capture for MCP traffic classification")
    default_iface = r"\Device\NPF_Loopback" if os.name == "nt" else ("lo0" if sys.platform == "darwin" else "lo")
    parser.add_argument("--interface", default=default_iface, help="Network interface to sniff on")
    parser.add_argument(
        "--ports-mcp",
        nargs="+",
        type=int,
        default=[8000],
        help="Port numbers used by MCP traffic",
    )
    parser.add_argument(
        "--ports-non-mcp",
        nargs="+",
        type=int,
        default=[5000, 5001, 5002],
        help="Port numbers used by non-MCP traffic",
    )
    parser.add_argument("--duration", type=int, default=30, help="Capture duration in seconds")
    parser.add_argument("--output-dir", default="data/pcap", help="Directory to save pcap files")
    args = parser.parse_args()

    capture_traffic(
        interface=args.interface,
        mcp_ports=args.ports_mcp,
        non_mcp_ports=args.ports_non_mcp,
        duration=args.duration,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    main()
