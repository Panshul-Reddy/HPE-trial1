# What Changed in This Project

Originally, all traffic was plain/unencrypted (HTTP). The big addition here was **TLS/HTTPS encryption support** — so the pipeline can now generate, capture, and classify *encrypted* traffic too.

---

## New Files Added

| File | What it does |
|------|-------------|
| `generate_certs.py` | Generates a self-signed TLS certificate (`certs/server.crt` + `certs/server.key`) for local testing |
| `certs/server.crt` | The public certificate (used by clients to verify the server) |
| `certs/server.key` | The private key (used by the server to encrypt traffic) |

---

## Files Modified

### `mcp_server/server.py`
- Added `--tls`, `--cert`, `--key` flags
- When `--tls` is set, the MCP server starts on **port 8443** over HTTPS instead of plain HTTP on port 8000

### `mcp_client/client.py`
- Added `--cert` flag so the client knows which certificate to trust
- Uses a custom HTTPS client (via `httpx`) to connect securely to `https://localhost:8443`

### `non_mcp_traffic/server.py`
- Added `--tls`, `--cert`, `--key` flags
- The Flask server now supports HTTPS on **port 5443** using Python's built-in `ssl` module

### `non_mcp_traffic/http_traffic.py`
- Added `--cert` flag
- Traffic generator now uses HTTPS and verifies the server certificate

### `traffic_capture/orchestrator.py`
- Coordinates everything — added `--tls` flag that automatically:
  - Starts MCP server on port 8443 (HTTPS)
  - Starts non-MCP server on port 5443 (HTTPS)
  - Passes the certificate to all clients
  - Tells the packet capture to watch the right ports

### `batch_generate.py`
- Added `--tls` flag that passes through to the orchestrator
- Also fixed a bug where the wrong Python (system instead of virtualenv) was used, causing MCP server subprocesses to silently crash

---

## How to Run

**Plain (unencrypted) pipeline — original:**
```bash
python batch_generate.py --target-rows 2000
```

**Encrypted (TLS) pipeline — new:**
```bash
# Step 0: Generate certs once
python generate_certs.py

# Step 1: Generate encrypted dataset
python batch_generate.py --target-rows 2000 --tls --pcap-dir data/pcap_tls --output data/tls_features.csv

# Step 2: Train model
python -m model.train --features data/tls_features.csv --output models/

# Step 3: Evaluate
python -m model.evaluate --model models/best_model.pkl --features data/tls_test_features.csv
```

---

## Key Finding

| Mode | Train Accuracy | Test Accuracy |
|------|---------------|---------------|
| Plain HTTP | ~99.8% | ~99.9% |
| Encrypted HTTPS | ~100% | **~66%** |

**Why the big drop?**  
In plain HTTP, MCP packets are ~5x larger than non-MCP packets — the model picks this up easily. TLS wraps everything in fixed-size records, hiding those size differences. The model overfit to patterns in the training data that don't generalize to new encrypted traffic.

**How to fix it:** Train on a combined plain + encrypted dataset so the model learns traffic patterns that hold up regardless of encryption.
