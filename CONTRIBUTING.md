# Contributing to MCP Traffic Classification Project

Thank you for your interest in contributing! This document explains how to set
up a development environment, run the pipeline, and submit changes.

---

## Development Setup

1. **Clone and create a virtual environment:**

   ```bash
   git clone https://github.com/AryanUrs/MCP_Project.git
   cd MCP_Project
   python3 -m venv .venv
   source .venv/bin/activate
   ```

2. **Install dependencies:**

   ```bash
   pip install -r requirements.txt
   ```

3. **Verify everything works:**

   ```bash
   python -c "import mcp, scapy, sklearn, pandas; print('OK')"
   ```

---

## Project Layout

| Directory | Purpose |
|---|---|
| `mcp_server/` | MCP server exposing tool endpoints over HTTP+SSE |
| `mcp_client/` | Traffic generator that calls MCP tools |
| `non_mcp_traffic/` | HTTP, WebSocket, and TCP servers & generators |
| `traffic_capture/` | Scapy-based packet capture and pipeline orchestrator |
| `feature_extraction/` | Converts pcap files into per-flow feature CSVs |
| `model/` | ML training (`train.py`) and evaluation (`evaluate.py`) |

---

## Running the Pipeline Locally

```bash
# Generate traffic + capture packets (requires sudo)
sudo python -m traffic_capture.orchestrator --duration 30 --requests 50

# Extract features
python -m feature_extraction.extractor --pcap-dir data/pcap --output data/features.csv

# Train models
python -m model.train --features data/features.csv --output models/
```

---

## Coding Conventions

- **Python 3.11+** — use modern type hints (e.g. `list[int]`, `dict[str, Any]`,
  `X | None` instead of `Optional[X]`).
- **Logging** — use the `logging` module (not `print`) for operational messages.
  Each module creates its own logger with `logging.getLogger(__name__)`.
- **CLI arguments** — every runnable module uses `argparse` with sensible
  defaults so it can be invoked with `python -m <package>.<module>`.
- **Docstrings** — every public function has a docstring explaining parameters
  and return values.

---

## Submitting Changes

1. Fork the repository and create a feature branch:

   ```bash
   git checkout -b feature/my-change
   ```

2. Make your changes and verify the pipeline still runs end-to-end.

3. Commit with a clear, descriptive message:

   ```bash
   git commit -m "Add new traffic generator for gRPC"
   ```

4. Push and open a pull request against `main`.

---

## Adding New Traffic Types

1. Create a new generator script in `non_mcp_traffic/` following the existing
   pattern (argparse CLI, async sessions, configurable request count).
2. If the new traffic requires a server, add it or extend
   `non_mcp_traffic/server.py`.
3. Register the new port in `traffic_capture/orchestrator.py` so the capture
   module labels the packets correctly.
4. Update `README.md` with usage instructions for the new component.

---

## Adding New ML Models

1. Edit `model/train.py` → `_build_classifiers()`.
2. Add your classifier to the `classifiers` dict. It must be scikit-learn
   compatible (implement `fit`, `predict`, and optionally `predict_proba`).
3. The training loop automatically handles cross-validation, evaluation, and
   model selection — no other changes are needed.
