# MCP Traffic Classification Project

A complete ML pipeline to classify **MCP (Model Context Protocol) vs non-MCP network traffic** using only network-level metadata features (no payload inspection).

---

## Table of Contents

- [Overview](#overview)
- [Architecture](#architecture)
- [Prerequisites](#prerequisites)
- [Getting Started](#getting-started)
- [Step-by-Step Tutorial](#step-by-step-tutorial)
- [Encrypted (TLS) Traffic](#encrypted-tls-traffic)
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
├── model/
│   ├── train.py                  # Train & evaluate Random Forest / XGBoost / Logistic Regression
│   └── evaluate.py               # Evaluate a saved model on new data
├── batch_generate.py             # Automated batch runner to generate large datasets (e.g. 10 000+ rows)
├── generate_certs.py             # Generates self-signed TLS certificate for encrypted traffic testing
├── certs/
│   └── server.crt                # Public TLS certificate (private key excluded from repo)
├── CHANGES.md                    # Plain-English summary of all TLS additions
└── results/
    ├── training_results.txt      # Saved training metrics for all classifiers
    └── evaluation_results.txt    # Saved evaluation metrics on unseen test data
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
| **cryptography** *(optional, for TLS)* | Required only if you want to generate encrypted traffic — installed automatically via `requirements.txt` |

### Platform notes

| Platform | Notes |
|---|---|
| **Linux** | Install `libpcap-dev` (`sudo apt install libpcap-dev`). On Ubuntu you may also need `build-essential` and `python3-dev` (`sudo apt install build-essential python3-dev`). Use `lo` as the capture interface. |
| **macOS** | Use `lo0` instead of `lo` (e.g. `--interface lo0`). You may need to install Xcode command-line tools (`xcode-select --install`). |
| **Windows** | Install [Npcap](https://npcap.com/) for Scapy packet capture. During installation, enable **"Support loopback traffic"** and **"WinPcap API-compatible Mode"**. Run commands in an **Administrator** PowerShell. The loopback interface is auto-detected; you can verify with `python -c "from scapy.all import get_if_list; print(get_if_list())"`. |

---

## Getting Started

### 1. Clone the repository

```bash
git clone https://github.com/Panshul-Reddy/HPE-trial1.git
cd HPE-trial1
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

> **Quick Start (3 commands):**
> ```bash
> # 1. Generate dataset (runs orchestrator + feature extraction internally)
> sudo .venv/bin/python batch_generate.py --target-rows 2000   # Linux
> # python batch_generate.py --target-rows 2000                 # Windows (Admin PowerShell)
>
> # 2. Train models
> python -m model.train
>
> # 3. Evaluate
> python -m model.evaluate --model models/best_model.pkl --features data/features.csv
> ```

### Step 1 — Generate training dataset

`batch_generate.py` handles the **entire data pipeline** automatically:
it starts all servers, generates traffic, captures packets, saves pcap files,
**and** extracts features into a CSV. You do **not** need to run the orchestrator
or feature extractor separately.

Each iteration randomizes traffic parameters (duration, request count, session
counts) to produce a **diverse, realistic dataset**.

**Linux / macOS:**
```bash
sudo python batch_generate.py --target-rows 10000
```

**Windows (Administrator PowerShell):**
```powershell
python batch_generate.py --target-rows 10000
```

This runs the orchestrator in a loop, extracting features after each iteration,
and stops once the target row count is reached. Output:
- `data/pcap/` — accumulated pcap files
- `data/features.csv` — training dataset (~10 000+ rows)

> **Tip:** Typical yield is ~1 500–2 000 flows per iteration. For 10 000 rows
> expect ~6 iterations taking ~7 minutes total.
>
> **Re-generating?** Delete old data first for a clean dataset:
> ```bash
> # Linux / macOS
> rm data/pcap/*.pcap data/features.csv models/*.pkl 2>/dev/null
> ```
> ```powershell
> # Windows
> Remove-Item data/pcap/*.pcap, data/features.csv, models/*.pkl -ErrorAction SilentlyContinue
> ```

<details>
<summary>Alternatively, run a single orchestrator pass (advanced — fewer rows, no auto-extraction)</summary>

**Linux:**
```bash
sudo python -m traffic_capture.orchestrator \
    --duration 60 \
    --requests 100 \
    --mcp-sessions 5 \
    --ws-sessions 3 \
    --tcp-connections 3 \
    --interface lo \
    --output-dir data/pcap
```

**macOS:**
```bash
sudo python -m traffic_capture.orchestrator \
    --duration 60 \
    --requests 100 \
    --mcp-sessions 5 \
    --ws-sessions 3 \
    --tcp-connections 3 \
    --interface lo0 \
    --output-dir data/pcap
```

**Windows (Administrator PowerShell):**
```powershell
python -m traffic_capture.orchestrator `
    --duration 60 `
    --requests 100 `
    --mcp-sessions 5 `
    --ws-sessions 3 `
    --tcp-connections 3 `
    --output-dir data/pcap
```

Then extract features manually:

```powershell
python -m feature_extraction.extractor `
    --pcap-dir data/pcap `
    --output data/features.csv
```

> **Note:** On Windows the loopback interface is auto-detected. You do not
> need `sudo` — just run from an **Administrator** PowerShell.

</details>

| Option | Default | Description |
|---|---|---|
| `--duration` | 60 | Traffic generation duration in seconds |
| `--requests` | 50 | Requests per generator |
| `--mcp-sessions` | 3 | Concurrent MCP client sessions |
| `--ws-sessions` | 3 | Concurrent WebSocket sessions |
| `--tcp-connections` | 3 | Concurrent TCP connections |
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

### Step 2 — Train models

Once `batch_generate.py` has finished, `data/features.csv` is ready.
The only manual step needed is training:

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
| **XGBoost** | 200 rounds, learning rate 0.1, GPU-accelerated (`device=cuda`) if available (falls back to Gradient Boosting if xgboost is not installed) |
| **Logistic Regression** | StandardScaler + L2 baseline |

The best model by weighted F1-score is saved to `models/best_model.pkl`.

> **Features used:** The CSV (`data/features.csv`) has one row per flow with
> 30+ features — flow duration, packet sizes, inter-arrival times, burst
> statistics, TCP flags, and idle time metrics. Port-related features
> (`src_port`, `dst_port`, `protocol`) are **automatically dropped during
> training** to prevent data leakage.

**Expected output (abbreviated):**

```
======================================================================
TRAINING AND EVALUATION
======================================================================

--- Random Forest ---
  CV F1 (mean ± std): 0.9789 ± 0.0043
  Accuracy:           0.9811  (98.1%)
  Precision:          0.9811
  Recall:             0.9811
  F1-score:           0.9811
  Misclassified:      42 / 2219
  ...

--- XGBoost ---
  Accuracy:           0.9806  (98.1%)
  ...

--- Logistic Regression ---
  Accuracy:           0.9793  (97.9%)
  ...

======================================================================
BEST MODEL: Random Forest
  Accuracy:  0.9811  (98.1%)
  F1-score:  0.9811
======================================================================

Top-10 feature importances:
pkt_size_mean     0.1694
total_bytes       0.1314
iat_std           0.1154
...

======================================================================
CLASS-WISE FEATURE COMPARISON (top distinguishing features)
======================================================================
  Feature                    mcp mean   non_mcp mean    Ratio
  --------------------------------------------------------
  burst_size_std                 6.85           1.49    4.59x
  pkt_size_max                2995.00         684.23    4.38x
  fwd_bytes                   5867.98        1621.87    3.62x
  pkt_size_std                 559.03         160.90    3.47x
  total_bytes                 8923.53        3267.68    2.73x
  ...

  Class balance:
    mcp            7197 samples  (69.1%)
    non_mcp        3215 samples  (30.9%)

  High accuracy is expected: the two traffic types differ by
  up to 4.6x on key features like burst_size_std,
  pkt_size_max, and fwd_bytes.
======================================================================
```

> The class-wise feature comparison provides justification for high model
> accuracy by showing how MCP and non-MCP traffic differ at the network
> metadata level. Features with near-zero means in both classes are excluded.

> Full training results are saved in `results/training_results.txt`.

### Step 3 — Evaluate on new data (robustness test)

Generate a completely separate test dataset that the model has **never seen**,
then evaluate against it:

**Linux / macOS:**
```bash
# Generate test dataset
sudo python batch_generate.py \
    --target-rows 2000 \
    --pcap-dir data/pcap_test \
    --output data/test_features.csv

# Evaluate the trained model on unseen data
python -m model.evaluate \
    --model models/best_model.pkl \
    --features data/test_features.csv
```

**Windows (Administrator PowerShell):**
```powershell
# Generate test dataset
python batch_generate.py `
    --target-rows 2000 `
    --pcap-dir data/pcap_test `
    --output data/test_features.csv

# Evaluate the trained model on unseen data
python -m model.evaluate `
    --model models/best_model.pkl `
    --features data/test_features.csv
```

> **Important:** The `--pcap-dir data/pcap_test` and `--output data/test_features.csv`
> flags ensure the test data goes to separate directories — your original
> training data in `data/features.csv` and `data/pcap/` is NOT overwritten.

Prints a classification report and confusion matrix. If the model supports
`predict_proba`, per-flow prediction probabilities are written to
`data/test_features_predictions.csv`.

**Expected output:**

```
============================================================
Evaluation on: data/test_features.csv
Model:         models/best_model.pkl
============================================================

  Accuracy:      0.9972  (99.7%)
  Precision:     0.9972
  Recall:        0.9972
  F1-score:      0.9972
  Misclassified: 6 / 2135

Classification Report:
              precision    recall  f1-score   support
         mcp       0.99      1.00      1.00      1180
     non_mcp       1.00      0.99      1.00       955
    accuracy                           1.00      2135

Confusion Matrix:
[[1180    0]
 [   6  949]]
```

> Full evaluation results are saved in `results/evaluation_results.txt`.

---

## Encrypted (TLS) Traffic

In addition to plain HTTP traffic, the pipeline supports **TLS/HTTPS encryption** — both MCP and non-MCP servers can be started in encrypted mode, and all clients will verify certificates automatically. This mirrors real-world deployments where traffic is encrypted in transit.

### Why encrypted traffic matters

Training a model on **only** plain HTTP traffic and then evaluating it on encrypted traffic drops accuracy from ~99.9% to ~66%. TLS wraps data in fixed-size records, masking the distinctive packet-size differences between MCP and non-MCP flows. The solution is to train on a **combined** dataset that includes both plain and encrypted samples.

| Training data | Test accuracy |
|---|---|
| Plain HTTP only | ~99.9% |
| Encrypted (TLS) only | ~66% |
| Combined (plain + TLS) | ~99%+ |

### Step 1 — Generate TLS certificates (once)

A self-signed certificate is included in `certs/server.crt`. To regenerate it (or if you cloned fresh and it is missing):

```powershell
python generate_certs.py
```

This creates:
- `certs/server.crt` — public certificate (committed to the repo)
- `certs/server.key` — private key (**never committed**, excluded by `.gitignore`)

The certificate is valid for `localhost` and `127.0.0.1`.

> **Note:** The private key file (`certs/server.key`) is excluded from version control for security reasons. You must run `generate_certs.py` once after cloning if you want to use TLS mode.

### Step 2 — Generate an encrypted dataset

Add `--tls` to any `batch_generate.py` command. Use separate `--pcap-dir` and `--output` paths to keep encrypted data separate from plain data:

**Windows (Administrator PowerShell):**
```powershell
python batch_generate.py `
    --target-rows 2000 `
    --tls `
    --pcap-dir data/pcap_tls `
    --output data/tls_features.csv
```

**Linux / macOS:**
```bash
sudo python batch_generate.py \
    --target-rows 2000 \
    --tls \
    --pcap-dir data/pcap_tls \
    --output data/tls_features.csv
```

When `--tls` is set, the orchestrator automatically:
- Starts the MCP server on **port 8443** (HTTPS)
- Starts the non-MCP server on **port 5443** (HTTPS)
- Passes the certificate to all clients for verification

### Step 3 — Train on encrypted data

```powershell
python -m model.train --features data/tls_features.csv --output models/
```

### Step 4 — Evaluate on encrypted test data

```powershell
# First generate a separate encrypted test set
python batch_generate.py `
    --target-rows 1000 `
    --tls `
    --pcap-dir data/pcap_tls_test `
    --output data/tls_test_features.csv

# Then evaluate
python -m model.evaluate `
    --model models/best_model.pkl `
    --features data/tls_test_features.csv
```

### Step 5 (Recommended) — Combined training for best accuracy

Train on both plain and encrypted data together. This is the recommended approach for a robust, production-ready model:

```powershell
# Merge the two datasets
python -c "
import pandas as pd
plain = pd.read_csv('data/features.csv')
tls   = pd.read_csv('data/tls_features.csv')
combined = pd.concat([plain, tls], ignore_index=True)
combined.to_csv('data/combined_features.csv', index=False)
print(f'Combined dataset: {len(combined)} rows')
"

# Train on combined data
python -m model.train --features data/combined_features.csv --output models/

# Evaluate on encrypted test set
python -m model.evaluate --model models/best_model.pkl --features data/tls_test_features.csv
```

---

## Running Components Individually

Each module can be run as a standalone command. This is useful for debugging,
developing new features, or generating traffic without the full orchestrator.

### MCP Server

**Plain HTTP (port 8000):**
```bash
python -m mcp_server.server --port 8000
```

**HTTPS / TLS (port 8443):**
```bash
python -m mcp_server.server --port 8443 --tls --cert certs/server.crt --key certs/server.key
```

Tools exposed: `add`, `subtract`, `multiply`, `divide`, `power`, `sqrt`,
`echo`, `echo_upper`, `echo_reversed`, `get_weather`, `get_forecast`,
`count_words`, `count_characters`, `to_title_case`, `replace_substring`,
`split_text`.

### MCP Client

**Plain HTTP:**
```bash
python -m mcp_client.client --url http://localhost:8000/sse --sessions 3 --requests 20
```

**HTTPS / TLS:**
```bash
python -m mcp_client.client --url https://localhost:8443/sse --sessions 3 --requests 20 --cert certs/server.crt
```

### Non-MCP Traffic Server

**Plain HTTP:**
```bash
python -m non_mcp_traffic.server --http-port 5000 --ws-port 5001
```

**HTTPS / TLS:**
```bash
python -m non_mcp_traffic.server --http-port 5443 --ws-port 5001 --tls --cert certs/server.crt --key certs/server.key
```

### HTTP Traffic Generator

**Plain HTTP:**
```bash
python -m non_mcp_traffic.http_traffic --url http://localhost:5000 --requests 50
```

**HTTPS / TLS:**
```bash
python -m non_mcp_traffic.http_traffic --url https://localhost:5443 --requests 50 --cert certs/server.crt
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
    --ws-sessions 6 \
    --tcp-connections 6 \
    --interface lo \
    --output-dir data/pcap
```

**Windows (Administrator PowerShell):**
```powershell
python -m traffic_capture.orchestrator `
    --duration 300 `
    --requests 500 `
    --mcp-sessions 10 `
    --ws-sessions 6 `
    --tcp-connections 6 `
    --output-dir data/pcap
```

You can run the orchestrator multiple times — pcap filenames include
timestamps, so new files are added alongside existing ones. The feature
extractor will process all pcap files in the directory.

### Batch generation (recommended for large datasets)

Use `batch_generate.py` to automatically loop the orchestrator until a
target row count is reached:

**Linux / macOS:**
```bash
sudo python batch_generate.py --target-rows 10000
```

**Windows (Administrator PowerShell):**
```powershell
python batch_generate.py --target-rows 10000
```

| Option | Default | Description |
|---|---|---|
| `--target-rows` | 10 000 | Stop once the CSV has this many rows |
| `--duration` | 60 | Base seconds per iteration (randomized 30–90s each run) |
| `--requests` | 500 | Base requests per generator (randomized 200–800 each run) |
| `--pcap-dir` | `data/pcap` | Directory for pcap files |
| `--output` | `data/features.csv` | Output CSV path |
| `--max-iterations` | 30 | Safety limit on iterations |

The script runs the orchestrator, extracts features, checks the row
count, and repeats until the target is met. Each iteration **randomizes**
session counts, duration, and requests to produce diverse traffic patterns.
Typical yield: **~1 500–2 000 flows per iteration** (balanced MCP / non-MCP).

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
│   ├── mcp_<timestamp>.pcap       # plain HTTP MCP packets (training)
│   └── non_mcp_<timestamp>.pcap   # plain HTTP non-MCP packets (training)
├── pcap_test/
│   ├── mcp_<timestamp>.pcap       # plain HTTP MCP packets (testing)
│   └── non_mcp_<timestamp>.pcap   # plain HTTP non-MCP packets (testing)
├── pcap_tls/
│   ├── mcp_<timestamp>.pcap       # encrypted MCP packets (training)
│   └── non_mcp_<timestamp>.pcap   # encrypted non-MCP packets (training)
├── pcap_tls_test/
│   ├── mcp_<timestamp>.pcap       # encrypted MCP packets (testing)
│   └── non_mcp_<timestamp>.pcap   # encrypted non-MCP packets (testing)
├── features.csv                   # plain HTTP training dataset
├── test_features.csv              # plain HTTP test dataset
├── tls_features.csv               # encrypted training dataset
├── tls_test_features.csv          # encrypted test dataset
└── combined_features.csv          # merged plain + encrypted dataset (recommended for training)
certs/
├── server.crt                     # public TLS certificate (tracked in git)
└── server.key                     # private TLS key (NOT tracked — regenerate with generate_certs.py)
models/
└── best_model.pkl                 # saved best classifier
results/
├── training_results.txt           # training metrics for all classifiers
└── evaluation_results.txt         # evaluation metrics on unseen test data
```

> `data/` and `models/` are in `.gitignore` because they are generated at
> runtime. `results/` is tracked in git so metrics are preserved.

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

**Linux / macOS:** Run the orchestrator (or `capture.py`) with `sudo`.

> **Important:** `sudo python` uses the **system** Python, not your virtual environment.
> Always pass the full path to the venv Python so the correct packages are found:

```bash
# Linux
sudo .venv/bin/python -m traffic_capture.orchestrator ...

# macOS
sudo .venv/bin/python -m traffic_capture.orchestrator --interface lo0 ...
```

Alternatively, grant raw-socket capability once and then run without `sudo`:

```bash
sudo setcap cap_net_raw+eip $(readlink -f .venv/bin/python)
python -m traffic_capture.orchestrator ...
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

### TLS / HTTPS issues

**`certs/server.key` not found:**  
The private key is excluded from the repo. Run `python generate_certs.py` once after cloning to create both `certs/server.crt` and `certs/server.key`.

**`[SSL: CERTIFICATE_VERIFY_FAILED]` in client:**  
Make sure you pass `--cert certs/server.crt` to the client (or `--tls` to `batch_generate.py`). The clients need the CA cert to verify the self-signed certificate.

**`Address already in use` on port 8443 or 5443:**  
A previous server run may still be running. Kill it with:
```powershell
# Windows — find and kill the process on port 8443
taskkill /F /PID (netstat -ano | findstr ":8443 " | ForEach-Object { ($_ -split '\s+')[-1] } | Select-Object -First 1)
```
```bash
# Linux / macOS
fuser -k 8443/tcp 5443/tcp
```

**Low accuracy on encrypted test data (~66%):**  
This is expected when training on plain HTTP only. See the [Encrypted (TLS) Traffic](#encrypted-tls-traffic) section — specifically Step 5 (Combined Training) — for the recommended fix.

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
