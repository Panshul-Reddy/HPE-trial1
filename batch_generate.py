"""
Batch traffic generation script.

Runs the orchestrator in a loop to accumulate pcap files, then extracts
features into a CSV.  Stops once the target number of rows is reached.

Usage (run from project root with venv activated, with elevated privileges):
  Windows  (Administrator PowerShell):
    python batch_generate.py                       # default 10 000 rows
    python batch_generate.py --target-rows 5000
  Linux / macOS  (use sudo with the venv Python):
    sudo .venv/bin/python batch_generate.py
    sudo .venv/bin/python batch_generate.py --target-rows 5000
"""

import argparse
import os
import random
import re
import subprocess
import sys
import time
from pathlib import Path

PCAP_DIR = "data/pcap"
OUTPUT_CSV = "data/features.csv"

# Per-run settings — base values; each iteration randomizes around these
DURATION = 60            # base seconds per run
REQUESTS = 500           # base requests per generator per run
MCP_SESSIONS = 8
WS_SESSIONS = 6
TCP_CONNECTIONS = 6

# Variation ranges (each iteration picks randomly within these)
_DURATION_RANGE = (30, 90)
_REQUESTS_RANGE = (200, 800)
_MCP_SESSIONS_RANGE = (2, 12)
_WS_SESSIONS_RANGE = (2, 10)
_TCP_CONNECTIONS_RANGE = (2, 10)


def _python() -> str:
    return sys.executable


def count_pcap_flows(pcap_dir: str) -> int:
    """Quick count of existing pcap files (rough proxy for flows available)."""
    d = Path(pcap_dir)
    if not d.exists():
        return 0
    return len([f for f in d.iterdir() if f.suffix == ".pcap"])


def extract_and_count(pcap_dir: str, output_csv: str) -> int:
    """Run feature extraction and return total row count."""
    result = subprocess.run(
        [
            _python(), "-m", "feature_extraction.extractor",
            "--pcap-dir", pcap_dir,
            "--output", output_csv,
        ],
        capture_output=True, text=True,
    )
    print(result.stdout)
    if result.stderr:
        # Print only the last few lines of stderr (logging output)
        lines = result.stderr.strip().split("\n")
        for line in lines[-5:]:
            print(line)

    if not Path(output_csv).exists():
        return 0

    # Count rows (subtract 1 for header)
    with open(output_csv, "r") as f:
        return sum(1 for _ in f) - 1


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch traffic generation for dataset")
    parser.add_argument(
        "--target-rows", type=int, default=10_000,
        help="Target number of rows in final CSV (default: 10000)",
    )
    parser.add_argument("--pcap-dir", default=PCAP_DIR, help="Directory for pcap files")
    parser.add_argument("--output", default=OUTPUT_CSV, help="Output CSV path")
    parser.add_argument(
        "--max-iterations", type=int, default=30,
        help="Safety limit on number of iterations",
    )
    parser.add_argument(
        "--duration", type=int, default=DURATION,
        help=f"Duration per run in seconds (default: {DURATION})",
    )
    parser.add_argument(
        "--requests", type=int, default=REQUESTS,
        help=f"Requests per generator per run (default: {REQUESTS})",
    )
    args = parser.parse_args()

    target = args.target_rows
    pcap_dir = args.pcap_dir
    output_csv = args.output

    Path(pcap_dir).mkdir(parents=True, exist_ok=True)

    print(f"=== Batch generator targeting {target} rows ===")
    print(f"    pcap dir : {pcap_dir}")
    print(f"    output   : {output_csv}")
    print(f"    per run  : duration={args.duration}s, requests={args.requests}")
    print()

    iteration = 0
    total_rows = 0

    while total_rows < target and iteration < args.max_iterations:
        iteration += 1

        # Randomize parameters this iteration for traffic diversity
        iter_duration = random.randint(*_DURATION_RANGE)
        iter_requests = random.randint(*_REQUESTS_RANGE)
        iter_mcp_sessions = random.randint(*_MCP_SESSIONS_RANGE)
        iter_ws_sessions = random.randint(*_WS_SESSIONS_RANGE)
        iter_tcp_connections = random.randint(*_TCP_CONNECTIONS_RANGE)

        print(f"--- Iteration {iteration} ---")
        print(f"  Params: duration={iter_duration}s, requests={iter_requests}, "
              f"mcp_sess={iter_mcp_sessions}, ws_sess={iter_ws_sessions}, tcp_conn={iter_tcp_connections}")
        t0 = time.time()

        # Run one orchestrator iteration
        cmd = [
            _python(), "-m", "traffic_capture.orchestrator",
            "--duration", str(iter_duration),
            "--requests", str(iter_requests),
            "--mcp-sessions", str(iter_mcp_sessions),
            "--ws-sessions", str(iter_ws_sessions),
            "--tcp-connections", str(iter_tcp_connections),
            "--output-dir", pcap_dir,
        ]
        print(f"  Running: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True)
        elapsed = time.time() - t0
        print(f"  Completed in {elapsed:.0f}s")

        if result.returncode != 0:
            print(f"  WARNING: orchestrator exited with code {result.returncode}")
            if result.stderr:
                for line in result.stderr.strip().split("\n")[-5:]:
                    print(f"    {line}")

        # Count pcap files accumulated so far
        pcap_count = count_pcap_flows(pcap_dir)
        print(f"  Total pcap files: {pcap_count}")

        # Extract features to get actual row count
        print("  Extracting features...")
        total_rows = extract_and_count(pcap_dir, output_csv)
        print(f"  Total rows so far: {total_rows} / {target}")
        print()

        if total_rows >= target:
            break

    # Final summary
    print("=" * 50)
    if total_rows >= target:
        print(f"SUCCESS: Generated {total_rows} rows in {iteration} iterations.")
    else:
        print(f"Stopped after {iteration} iterations with {total_rows} rows.")
    print(f"Dataset saved to: {output_csv}")


if __name__ == "__main__":
    main()
