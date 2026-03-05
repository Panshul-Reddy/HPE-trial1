# MCP Traffic Classification Project

A complete ML pipeline to classify **MCP (Model Context Protocol) vs non-MCP network traffic** using only network-level metadata features (no payload inspection).

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

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** Packet capture requires `scapy` and **root / Administrator privileges** on most operating systems.

---

### 2. Run the full pipeline (automated)

The orchestrator starts all servers, generates traffic, captures packets, and saves labelled pcap files:

```bash
sudo python -m traffic_capture.orchestrator \
    --duration 60 \
    --requests 100 \
    --mcp-sessions 5 \
    --interface lo \
    --output-dir data/pcap
```

| Option | Default | Description |
|---|---|---|
| `--duration` | 60 | Traffic generation duration in seconds |
| `--requests` | 50 | Requests per generator |
| `--mcp-sessions` | 3 | Concurrent MCP client sessions |
| `--interface` | `lo` | Network interface to capture on |
| `--output-dir` | `data/pcap` | Where pcap files are saved |
| `--no-capture` | — | Skip packet capture, only generate traffic |

---

### 3. Extract features

```bash
python -m feature_extraction.extractor \
    --pcap-dir data/pcap \
    --output data/features.csv
```

Produces a CSV with one row per network flow and the following feature columns:

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

---

### 4. Train models

```bash
python -m model.train \
    --features data/features.csv \
    --output models/ \
    --test-size 0.2 \
    --cv-folds 5
```

Three classifiers are compared:

| Classifier | Notes |
|---|---|
| **Random Forest** | 200 trees, no depth limit |
| **XGBoost** | 200 rounds, learning rate 0.1 (falls back to Gradient Boosting if xgboost is not installed) |
| **Logistic Regression** | StandardScaler + L2 baseline |

The best model by weighted F1-score is saved to `models/best_model.pkl`.

---

### 5. Evaluate a saved model

```bash
python -m model.evaluate \
    --model models/best_model.pkl \
    --features data/new_features.csv
```

Prints a classification report and confusion matrix. If the model supports `predict_proba`, per-flow prediction probabilities are written to `<features>_predictions.csv`.

---

## Running components individually

### MCP Server

```bash
python -m mcp_server.server --port 8000
```

Tools exposed: `add`, `subtract`, `multiply`, `divide`, `power`, `sqrt`, `echo`, `echo_upper`, `echo_reversed`, `get_weather`, `get_forecast`, `count_words`, `count_characters`, `to_title_case`, `replace_substring`, `split_text`.

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

## Data directory layout

```
data/
├── pcap/
│   ├── mcp_<timestamp>.pcap       # captured MCP packets
│   └── non_mcp_<timestamp>.pcap   # captured non-MCP packets
└── features.csv                   # extracted per-flow features
models/
└── best_model.pkl                 # saved best classifier
```

---

## Requirements

- Python 3.11+
- Root / Administrator privileges for packet capture (`scapy`)
- See `requirements.txt` for full dependency list
