# MCP Traffic Classification Project

A complete ML pipeline to classify **MCP (Model Context Protocol) vs non-MCP network traffic** using only network-level metadata features (no payload inspection).

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Step-by-Step Tutorial](#step-by-step-tutorial)
- [Running Components Individually](#running-components-individually)
- [Customizing the Project](#customizing-the-project)
- [Data Directory Layout](#data-directory-layout)
- [Troubleshooting](#troubleshooting)
- [Contributing](#contributing)

---

## Overview

This project builds a machine-learning classifier that distinguishes MCP
(Model Context Protocol) traffic from regular HTTP, WebSocket, and TCP traffic
**using only network-level metadata** — packet sizes, inter-arrival times,
TCP flags, and similar features. No payload inspection (deep packet inspection)
is performed, making the approach practical for real-world deployments.

The pipeline has four stages:

1. **Traffic Generation** — start MCP and non-MCP servers, then drive traffic
   through them.
2. **Packet Capture** — sniff packets on the loopback interface with
   [Scapy](https://scapy.net/) and save labelled pcap files.
3. **Feature Extraction** — read pcap files, group packets into flows, and
   compute 30+ statistical features per flow.
4. **Model Training & Evaluation** — train Random Forest, XGBoost, and
   Logistic Regression classifiers, pick the best by F1-score, and evaluate
   on held-out data.

---

## Architecture

```
MCP_Project/
├── requirements.txt              # Python dependencies
├── mcp_server/
│   └── server.py                 # MCP server (calculator, echo, weather, string utils) — HTTP+SSE
├── mcp_client/
│   └── client.py                 # MCP client that generates realistic tool-call traffic
├── non_mcp_traffic/
│   ├── server.py                 # HTTP REST + WebSocket server
│   ├── http_traffic.py           # HTTP GET/POST/PUT/DELETE traffic generator
│   ├── websocket_traffic.py      # WebSocket traffic generator
│   └── tcp_traffic.py            # Raw TCP traffic generator
├── traffic_capture/
│   ├── capture.py                # Scapy-based packet capture → labelled pcap files
│   └── orchestrator.py           # End-to-end pipeline orchestrator
├── feature_extraction/
│   └── extractor.py              # Per-flow feature extraction pcap → CSV
└── model/
    ├── train.py                  # Train & evaluate Random Forest / XGBoost / Logistic Regression
    └── evaluate.py               # Evaluate a saved model on new data
```

---

## Prerequisites

| Requirement | Why |
|---|---|
| **Python 3.11+** | Required by the `mcp` SDK and type-hint syntax used throughout the project |
| **pip** | To install Python dependencies from `requirements.txt` |
| **Root / Administrator privileges** | Scapy needs raw-socket access for packet capture (`sudo` on Linux/macOS) |
| **Loopback interface** (`lo` on Linux, `lo0` on macOS, auto-detected on Windows) | Default capture interface; all servers bind to `localhost` |
| **Git** | To clone this repository |

### Platform notes

| Platform | Notes |
|---|---|
| **Linux** | Works out of the box. Use `lo` as the capture interface. |
| **macOS** | Use `lo0` instead of `lo` (e.g. `--interface lo0`). You may need to install Xcode command-line tools (`xcode-select --install`). |
| **Windows** | Install [Npcap](https://npcap.com/) for Scapy packet capture. During installation, enable **"Support loopback traffic"** and **"WinPcap API-compatible Mode"**. Run commands in an **Administrator** PowerShell. The loopback interface is auto-detected; you can verify with `python -c "from scapy.all import get_if_list; print(get_if_list())"`. |

---

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/AryanUrs/MCP_Project.git
cd MCP_Project
```

### 2. Create a virtual environment (recommended)

**Linux / macOS:**
```bash
python3 -m venv .venv
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Verify the installation

```bash
python -c "import mcp, scapy, sklearn, pandas; print('All dependencies OK')"
```

You should see:

```
All dependencies OK
```

> **Tip:** If `xgboost` fails to install on your platform, the training module
> will automatically fall back to scikit-learn's `GradientBoostingClassifier`.

---

## Step-by-Step Tutorial

This section walks through the **entire pipeline** from traffic generation to
model evaluation. Each step can also be run independently — see
[Running Components Individually](#running-components-individually).

### Step 1 — Generate traffic and capture packets

The orchestrator starts all servers, generates traffic, captures packets, and
saves labelled pcap files — all in one command:

**Linux:**
```bash
sudo python -m traffic_capture.orchestrator \
    --duration 60 \
    --requests 100 \
    --mcp-sessions 5 \
    --interface lo \
    --output-dir data/pcap
```

**macOS:**
```bash
sudo python -m traffic_capture.orchestrator \
    --duration 60 \
    --requests 100 \
    --mcp-sessions 5 \
    --interface lo0 \
    --output-dir data/pcap
```

**Windows (Administrator PowerShell):**
```powershell
python -m traffic_capture.orchestrator `
    --duration 60 `
    --requests 100 `
    --mcp-sessions 5 `
    --output-dir data/pcap
```

> **Note:** On Windows the loopback interface is auto-detected. You do not
> need `sudo` — just run from an **Administrator** PowerShell.

| Option | Default | Description |
|---|---|---|
| `--duration` | 60 | Traffic generation duration in seconds |
| `--requests` | 50 | Requests per generator |
| `--mcp-sessions` | 3 | Concurrent MCP client sessions |
| `--interface` | auto-detected | Network interface to capture on (`lo` on Linux, `lo0` on macOS, `\Device\NPF_Loopback` on Windows) |
| `--output-dir` | `data/pcap` | Where pcap files are saved |
| `--no-capture` | — | Skip packet capture, only generate traffic |

**Expected output:**

```
2025-01-15 10:00:01 INFO Starting: python -m mcp_server.server --port 8000
2025-01-15 10:00:01 INFO Starting: python -m non_mcp_traffic.server ...
2025-01-15 10:00:02 INFO Waiting for servers to start…
2025-01-15 10:00:04 INFO Generating traffic for 60 seconds…
2025-01-15 10:01:04 INFO Traffic generation complete.
2025-01-15 10:01:05 INFO Pipeline finished. pcap files are in: data/pcap
```

After this step, `data/pcap/` will contain files like:

```
data/pcap/mcp_1705312800.pcap
data/pcap/non_mcp_1705312800.pcap
```

### Step 2 — Extract features

**Linux / macOS:**
```bash
python -m feature_extraction.extractor \
    --pcap-dir data/pcap \
    --output data/features.csv
```

**Windows (PowerShell):**
```powershell
python -m feature_extraction.extractor `
    --pcap-dir data/pcap `
    --output data/features.csv
```

This reads every pcap file in `data/pcap/`, groups packets into network flows
(by 5-tuple: src IP, dst IP, src port, dst port, protocol), and computes 30+
features per flow.

**Expected output:**

```
2025-01-15 10:02:00 INFO Reading data/pcap/mcp_1705312800.pcap (label=mcp)
2025-01-15 10:02:00 INFO   1420 packets loaded
2025-01-15 10:02:00 INFO   12 flows extracted
2025-01-15 10:02:01 INFO Reading data/pcap/non_mcp_1705312800.pcap (label=non_mcp)
2025-01-15 10:02:01 INFO   2380 packets loaded
2025-01-15 10:02:01 INFO   35 flows extracted
2025-01-15 10:02:01 INFO Saved 47 flows (12 MCP, 35 non-MCP) to data/features.csv
```

The resulting CSV (`data/features.csv`) has one row per flow with these
columns:

| Category | Features |
|---|---|
| Flow metadata | `flow_duration`, `total_packets`, `fwd_packets`, `bwd_packets` |
| Byte counts | `total_bytes`, `fwd_bytes`, `bwd_bytes`, `flow_asymmetry` |
| Packet size | `pkt_size_{mean,std,min,max,median}` |
| Inter-arrival time | `iat_{mean,std,min,max}` |
| Burst analysis | `burst_count`, `burst_size_{mean,std}` |
| TCP flags | `flag_{SYN,ACK,PSH,FIN,RST}` |
| Packet counts | `small_packets` (< 100 B), `large_packets` (> 1 000 B) |
| Idle time | `idle_time_{mean,std,max}` |
| Ports | `src_port`, `dst_port`, `protocol` |

### Step 3 — Train models

**Linux / macOS:**
```bash
python -m model.train \
    --features data/features.csv \
    --output models/ \
    --test-size 0.2 \
    --cv-folds 5
```

**Windows (PowerShell):**
```powershell
python -m model.train `
    --features data/features.csv `
    --output models/ `
    --test-size 0.2 `
    --cv-folds 5
```

Three classifiers are compared:

| Classifier | Notes |
|---|---|
| **Random Forest** | 200 trees, no depth limit |
| **XGBoost** | 200 rounds, learning rate 0.1 (falls back to Gradient Boosting if xgboost is not installed) |
| **Logistic Regression** | StandardScaler + L2 baseline |

The best model by weighted F1-score is saved to `models/best_model.pkl`.

**Expected output (abbreviated):**

```
======================================================================
TRAINING AND EVALUATION
======================================================================

--- Random Forest ---
  CV F1 (mean ± std): 0.9812 ± 0.0134
  Test F1 (weighted): 0.9850
              precision    recall  f1-score   support
         mcp       0.98      0.99      0.98        12
     non_mcp       0.99      0.98      0.99        35
  ...

--- XGBoost ---
  ...

--- Logistic Regression ---
  ...

======================================================================
BEST MODEL: Random Forest  (test F1 = 0.9850)
======================================================================

Top-10 feature importances:
pkt_size_mean      0.1842
iat_mean           0.1234
...
```

### Step 4 — Evaluate on new data

**Linux / macOS:**
```bash
python -m model.evaluate \
    --model models/best_model.pkl \
    --features data/features.csv
```

**Windows (PowerShell):**
```powershell
python -m model.evaluate `
    --model models/best_model.pkl `
    --features data/features.csv
```

Prints a classification report and confusion matrix. If the model supports
`predict_proba`, per-flow prediction probabilities are written to
`data/features_predictions.csv`.

**Expected output:**

```
============================================================
Evaluation on: data/features.csv
Model:         models/best_model.pkl
============================================================

Weighted F1-score: 0.9850

Classification Report:
              precision    recall  f1-score   support
         mcp       0.98      0.99      0.98        12
     non_mcp       0.99      0.98      0.99        35
    accuracy                           0.98        47
   macro avg       0.98      0.98      0.98        47
weighted avg       0.99      0.98      0.99        47

Confusion Matrix:
[[12  0]
 [ 1 34]]
```

---

## Running Components Individually

Each module can be run as a standalone command. This is useful for debugging,
developing new features, or generating traffic without the full orchestrator.

### MCP Server

```bash
python -m mcp_server.server --port 8000
```

Tools exposed: `add`, `subtract`, `multiply`, `divide`, `power`, `sqrt`,
`echo`, `echo_upper`, `echo_reversed`, `get_weather`, `get_forecast`,
`count_words`, `count_characters`, `to_title_case`, `replace_substring`,
`split_text`.

### MCP Client

```bash
python -m mcp_client.client --url http://localhost:8000/sse --sessions 3 --requests 20
```

### Non-MCP Traffic Server

```bash
python -m non_mcp_traffic.server --http-port 5000 --ws-port 5001
```

### HTTP Traffic Generator

```bash
python -m non_mcp_traffic.http_traffic --url http://localhost:5000 --requests 50
```

### WebSocket Traffic Generator

```bash
python -m non_mcp_traffic.websocket_traffic --url ws://localhost:5001 --sessions 2 --messages 30
```

### TCP Traffic Generator

```bash
python -m non_mcp_traffic.tcp_traffic --host localhost --port 5002 --connections 3 --messages 10
```

---

## Customizing the Project

### Increase the dataset size

Generate more traffic by raising `--duration` and `--requests`:

**Linux:**
```bash
sudo python -m traffic_capture.orchestrator \
    --duration 300 \
    --requests 500 \
    --mcp-sessions 10 \
    --interface lo \
    --output-dir data/pcap
```

**Windows (Administrator PowerShell):**
```powershell
python -m traffic_capture.orchestrator `
    --duration 300 `
    --requests 500 `
    --mcp-sessions 10 `
    --output-dir data/pcap
```

You can run the orchestrator multiple times — pcap filenames include
timestamps, so new files are added alongside existing ones. The feature
extractor will process all pcap files in the directory.

### Add new MCP tools

Edit `mcp_server/server.py` and register a new tool with the `@mcp.tool()`
decorator:

```python
@mcp.tool()
def my_new_tool(param: str) -> str:
    """Description of your new tool."""
    return f"Result: {param}"
```

The MCP client (`mcp_client/client.py`) discovers tools dynamically via
`session.list_tools()`, but you may also want to add a helper function
(similar to `_random_calculator_call`) to generate targeted traffic for
your new tool.

### Add new non-MCP traffic types

1. Create a new generator file in `non_mcp_traffic/` (follow the pattern in
   `http_traffic.py`).
2. Start the corresponding server (or reuse the existing one).
3. Register the port in `traffic_capture/orchestrator.py` so the packet
   capture module labels the traffic correctly.

### Tune the ML models

Edit `model/train.py` → `_build_classifiers()` to change hyper-parameters or
add new classifiers. Any scikit-learn-compatible estimator works — just add it
to the `classifiers` dictionary.

### Use your own pcap files

If you already have labelled pcap files, place them in a directory following
the naming convention `mcp_*.pcap` and `non_mcp_*.pcap`, then run the feature
extractor directly:

```bash
python -m feature_extraction.extractor \
    --pcap-dir /path/to/your/pcaps \
    --output data/features.csv
```

**Windows:**
```powershell
python -m feature_extraction.extractor `
    --pcap-dir C:\path\to\your\pcaps `
    --output data/features.csv
```

---

## Data Directory Layout

```
data/
├── pcap/
│   ├── mcp_<timestamp>.pcap       # captured MCP packets
│   └── non_mcp_<timestamp>.pcap   # captured non-MCP packets
└── features.csv                   # extracted per-flow features
models/
└── best_model.pkl                 # saved best classifier
```

> Both `data/` and `models/` are in `.gitignore` because they are generated at
> runtime.

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'mcp'`

Make sure you installed all dependencies inside an active virtual environment:

**Linux / macOS:**
```bash
source .venv/bin/activate
pip install -r requirements.txt
```

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### `PermissionError` or `Operation not permitted` during packet capture

Scapy needs raw-socket access.

**Linux / macOS:** Run the orchestrator (or `capture.py`) with `sudo`:

```bash
sudo python -m traffic_capture.orchestrator ...
```

On macOS with a virtual environment, pass the full path to the venv Python:

```bash
sudo .venv/bin/python -m traffic_capture.orchestrator --interface lo0 ...
```

**Windows:** Run PowerShell as **Administrator** (right-click → *Run as administrator*) and ensure [Npcap](https://npcap.com/) is installed:

```powershell
python -m traffic_capture.orchestrator ...
```

### `OSError: No such device` (wrong network interface)

Use `lo` on Linux, `lo0` on macOS, or omit `--interface` on Windows
(it auto-detects `\Device\NPF_Loopback`). To list available interfaces:

```bash
python -c "from scapy.all import get_if_list; print(get_if_list())"
```

### Empty pcap files / no flows extracted

- Ensure the servers started successfully (check for port-conflict errors).
- Increase `--duration` and `--requests` to generate more traffic.
- Verify the capture interface matches where traffic flows (use `lo` /
  `lo0` when servers bind to `localhost`).

### `xgboost` installation fails

The training module falls back to scikit-learn's `GradientBoostingClassifier`
automatically. You can safely ignore the `xgboost` install error and
proceed.

### Low F1-score or poor model performance

- Generate more data — the default 60-second capture may produce too few
  flows for a robust model.
- Try increasing `--cv-folds` for a better estimate of generalisation.
- Inspect `data/features.csv` for class imbalance and consider adjusting
  `--requests` or `--mcp-sessions` to balance the traffic mix.

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development guidelines and
contribution workflow.

---

## Requirements

- Python 3.11+
- Root / Administrator privileges for packet capture (`scapy`)
- See `requirements.txt` for full dependency list
