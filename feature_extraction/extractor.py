"""
Feature extraction from pcap files.

Reads labelled pcap files (mcp_*.pcap / non_mcp_*.pcap) from a directory,
groups packets into per-flow records (5-tuple: src_ip, dst_ip, src_port,
dst_port, protocol), and extracts a rich set of network-level features.

No payload inspection is performed – only packet metadata (sizes, timings,
TCP flags, port numbers) is used.

Output: a CSV file with one row per flow and a 'label' column ('mcp' or
'non_mcp').

Usage:
    python -m feature_extraction.extractor --pcap-dir data/pcap --output data/features.csv
"""

import argparse
import logging
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

BURST_GAP_THRESHOLD = 0.5   # seconds – inter-packet gap considered a burst boundary
IDLE_GAP_THRESHOLD = 1.0    # seconds – inter-packet gap considered idle time


# ---------------------------------------------------------------------------
# Flow key helpers
# ---------------------------------------------------------------------------

FlowKey = tuple  # (src_ip, dst_ip, src_port, dst_port, proto)


def _flow_key(pkt) -> FlowKey | None:
    """Return the bidirectional flow key for a packet (or None if not TCP/UDP)."""
    from scapy.layers.inet import IP, TCP, UDP

    if not pkt.haslayer(IP):
        return None
    ip = pkt[IP]
    if pkt.haslayer(TCP):
        l4 = pkt[TCP]
        proto = 6
    elif pkt.haslayer(UDP):
        l4 = pkt[UDP]
        proto = 17
    else:
        return None

    # Normalise direction: sort (src, sport) / (dst, dport)
    ep1 = (ip.src, l4.sport)
    ep2 = (ip.dst, l4.dport)
    if ep1 <= ep2:
        return (ip.src, ip.dst, l4.sport, l4.dport, proto)
    return (ip.dst, ip.src, l4.dport, l4.sport, proto)


# ---------------------------------------------------------------------------
# Packet record extraction
# ---------------------------------------------------------------------------

def _pkt_size(pkt) -> int:
    return len(pkt)


def _tcp_flags(pkt) -> dict[str, int]:
    from scapy.layers.inet import TCP

    if not pkt.haslayer(TCP):
        return {"SYN": 0, "ACK": 0, "PSH": 0, "FIN": 0, "RST": 0}
    flags = pkt[TCP].flags
    return {
        "SYN": int(flags.S),
        "ACK": int(flags.A),
        "PSH": int(flags.P),
        "FIN": int(flags.F),
        "RST": int(flags.R),
    }


def _is_forward(pkt, fwd_src: str, fwd_sport: int) -> bool:
    from scapy.layers.inet import IP, TCP, UDP

    if not pkt.haslayer(IP):
        return True
    ip = pkt[IP]
    l4 = pkt[TCP] if pkt.haslayer(TCP) else pkt[UDP] if pkt.haslayer(UDP) else None
    if l4 is None:
        return True
    return ip.src == fwd_src and l4.sport == fwd_sport


# ---------------------------------------------------------------------------
# Feature computation
# ---------------------------------------------------------------------------

def _safe_stats(arr: list[float]) -> dict[str, float]:
    if not arr:
        return {"mean": 0.0, "std": 0.0, "min": 0.0, "max": 0.0, "median": 0.0}
    a = np.array(arr, dtype=float)
    return {
        "mean": float(np.mean(a)),
        "std": float(np.std(a)),
        "min": float(np.min(a)),
        "max": float(np.max(a)),
        "median": float(np.median(a)),
    }


def _compute_flow_features(
    packets: list,  # list of (timestamp, pkt)
    label: str,
    flow_key: FlowKey,
) -> dict[str, Any]:
    src_ip, dst_ip, src_port, dst_port, proto = flow_key
    timestamps = [ts for ts, _ in packets]
    pkts = [p for _, p in packets]

    flow_duration = timestamps[-1] - timestamps[0] if len(timestamps) > 1 else 0.0
    sizes = [_pkt_size(p) for p in pkts]

    # Forward / backward split
    fwd_sizes, bwd_sizes = [], []
    for ts, p in packets:
        if _is_forward(p, src_ip, src_port):
            fwd_sizes.append(_pkt_size(p))
        else:
            bwd_sizes.append(_pkt_size(p))

    total_bytes = sum(sizes)
    fwd_bytes = sum(fwd_sizes)
    bwd_bytes = sum(bwd_sizes)
    asymmetry = fwd_bytes / total_bytes if total_bytes > 0 else 0.0

    # Inter-arrival times
    iats = [timestamps[i] - timestamps[i - 1] for i in range(1, len(timestamps))]

    # TCP flags
    flag_totals = {"SYN": 0, "ACK": 0, "PSH": 0, "FIN": 0, "RST": 0}
    for p in pkts:
        for k, v in _tcp_flags(p).items():
            flag_totals[k] += v

    # Burst analysis
    burst_count = 0
    burst_sizes: list[int] = []
    current_burst_size = 1
    for iat in iats:
        if iat < BURST_GAP_THRESHOLD:
            current_burst_size += 1
        else:
            burst_sizes.append(current_burst_size)
            burst_count += 1
            current_burst_size = 1
    burst_sizes.append(current_burst_size)
    if iats:
        burst_count += 1

    idle_times = [iat for iat in iats if iat >= IDLE_GAP_THRESHOLD]

    size_stats = _safe_stats(sizes)
    iat_stats = _safe_stats(iats)
    burst_stats = _safe_stats([float(s) for s in burst_sizes])
    idle_stats = _safe_stats(idle_times)

    return {
        # Flow identifiers
        "src_ip": src_ip,
        "dst_ip": dst_ip,
        "src_port": src_port,
        "dst_port": dst_port,
        "protocol": proto,
        # Duration & counts
        "flow_duration": flow_duration,
        "total_packets": len(pkts),
        "fwd_packets": len(fwd_sizes),
        "bwd_packets": len(bwd_sizes),
        "total_bytes": total_bytes,
        "fwd_bytes": fwd_bytes,
        "bwd_bytes": bwd_bytes,
        # Packet size stats
        "pkt_size_mean": size_stats["mean"],
        "pkt_size_std": size_stats["std"],
        "pkt_size_min": size_stats["min"],
        "pkt_size_max": size_stats["max"],
        "pkt_size_median": size_stats["median"],
        # IAT stats
        "iat_mean": iat_stats["mean"],
        "iat_std": iat_stats["std"],
        "iat_min": iat_stats["min"],
        "iat_max": iat_stats["max"],
        # Asymmetry
        "flow_asymmetry": asymmetry,
        # Burst stats
        "burst_count": burst_count,
        "burst_size_mean": burst_stats["mean"],
        "burst_size_std": burst_stats["std"],
        # TCP flags
        "flag_SYN": flag_totals["SYN"],
        "flag_ACK": flag_totals["ACK"],
        "flag_PSH": flag_totals["PSH"],
        "flag_FIN": flag_totals["FIN"],
        "flag_RST": flag_totals["RST"],
        # Small / large packets
        "small_packets": sum(1 for s in sizes if s < 100),
        "large_packets": sum(1 for s in sizes if s > 1000),
        # Idle time stats
        "idle_time_mean": idle_stats["mean"],
        "idle_time_std": idle_stats["std"],
        "idle_time_max": idle_stats["max"],
        # Label
        "label": label,
    }


# ---------------------------------------------------------------------------
# PCAP reading & flow assembly
# ---------------------------------------------------------------------------

def _label_from_filename(filename: str) -> str:
    """Infer label from pcap filename: 'mcp' or 'non_mcp'."""
    name = Path(filename).name.lower()
    if name.startswith("mcp"):
        return "mcp"
    if name.startswith("non_mcp"):
        return "non_mcp"
    raise ValueError(
        f"Cannot infer label from filename '{name}'. "
        "Expected mcp_*.pcap or non_mcp_*.pcap"
    )


def extract_features_from_pcap(pcap_path: str, label: str | None = None) -> pd.DataFrame:
    """
    Read a single pcap file and return a DataFrame of per-flow features.

    Parameters
    ----------
    pcap_path : path to the .pcap file
    label     : 'mcp' or 'non_mcp'. If None, inferred from filename.
    """
    try:
        from scapy.all import rdpcap
    except ImportError as exc:
        raise ImportError("scapy is required. Install with: pip install scapy") from exc

    if label is None:
        label = _label_from_filename(pcap_path)

    logger.info("Reading %s (label=%s)", pcap_path, label)
    packets = rdpcap(pcap_path)
    logger.info("  %d packets loaded", len(packets))

    # Group packets by flow
    flows: dict[FlowKey, list[tuple[float, Any]]] = defaultdict(list)
    for pkt in packets:
        key = _flow_key(pkt)
        if key is None:
            continue
        ts = float(pkt.time)
        flows[key].append((ts, pkt))

    # Sort each flow by timestamp
    for key in flows:
        flows[key].sort(key=lambda x: x[0])

    logger.info("  %d flows extracted", len(flows))

    rows = [
        _compute_flow_features(flow_pkts, label, key)
        for key, flow_pkts in flows.items()
    ]

    return pd.DataFrame(rows)


def extract_features_from_directory(
    pcap_dir: str,
    output_csv: str,
    mcp_pattern: str = r"^mcp.*\.pcap$",
    non_mcp_pattern: str = r"^non_mcp.*\.pcap$",
) -> pd.DataFrame:
    """
    Process all pcap files in *pcap_dir* and write a combined CSV to *output_csv*.
    """
    pcap_dir_path = Path(pcap_dir)
    all_frames: list[pd.DataFrame] = []

    for fname in sorted(os.listdir(pcap_dir_path)):
        fpath = str(pcap_dir_path / fname)
        if re.match(mcp_pattern, fname, re.IGNORECASE):
            label = "mcp"
        elif re.match(non_mcp_pattern, fname, re.IGNORECASE):
            label = "non_mcp"
        else:
            continue

        df = extract_features_from_pcap(fpath, label=label)
        all_frames.append(df)

    if not all_frames:
        logger.warning("No pcap files found in %s", pcap_dir)
        return pd.DataFrame()

    combined = pd.concat(all_frames, ignore_index=True)
    Path(output_csv).parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(output_csv, index=False)
    logger.info(
        "Saved %d flows (%d MCP, %d non-MCP) to %s",
        len(combined),
        (combined["label"] == "mcp").sum(),
        (combined["label"] == "non_mcp").sum(),
        output_csv,
    )
    return combined


def main() -> None:
    parser = argparse.ArgumentParser(description="Feature extraction from pcap files")
    parser.add_argument("--pcap-dir", default="data/pcap", help="Directory containing pcap files")
    parser.add_argument(
        "--output", default="data/features.csv", help="Output CSV file path"
    )
    args = parser.parse_args()

    extract_features_from_directory(args.pcap_dir, args.output)


if __name__ == "__main__":
    main()
