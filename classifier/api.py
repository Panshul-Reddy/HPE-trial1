
"""
FastFlow Early Inference API (Machine Learning Engine)

This module implements an asynchronous FastAPI server that hosts pre-trained tree
ensemble sequence models. It provides low-latency inference for the Rust feature
extractor, dynamically selecting the appropriate N-packet threshold model based on
the number of observed packets in the network flow.
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
import joblib
import numpy as np
import os
import time
from collections import deque
from typing import Optional

app = FastAPI(title="FastFlow Early Inference API")

THRESHOLDS = [3, 5, 8, 10, 15, 20]
models = {}

# --- State for Dashboard ---
START_TIME = time.time()
TOTAL_FLOWS = 0
TOTAL_MCP = 0
TOTAL_NOISE = 0
TOTAL_WITH_GT = 0
CORRECT_PREDS = 0
LATENCY_SAMPLES = deque(maxlen=1000)

class FlowRecord(BaseModel):
    flow_display: str
    label: int
    proba_mcp: float
    proba_noise: float
    pkt_count: int
    duration_s: float
    ground_truth: Optional[int] = None
    inference_latency: float

# Keep last 500 flows
RECENT_FLOWS = deque(maxlen=500)
ACTIVE_PREDICTIONS = {}  # flow_display -> (label, ground_truth)


def load_serialized_model(path: str):
    if path.endswith(".joblib"):
        return joblib.load(path)

    import xgboost as xgb

    model = xgb.XGBClassifier()
    model.load_model(path)
    return model

def get_feature_indices(n: int) -> list[int]:
    """
    Maps the progressive feature indices to the 115-dimension array sent by the Rust core.
    """
    indices = list(range(15)) # Base 15 features
    for i in range(n):
        indices.append(15 + i) # seq_size
        indices.append(35 + i) # seq_dir
        indices.append(55 + i) # seq_iat
    return indices

@app.on_event("startup")
def load_models():
    for n in THRESHOLDS:
        path = f"models/n{n}.joblib"
        legacy_path = f"models/xgb_n{n}.json"
        if os.path.exists(path):
            m = load_serialized_model(path)
            models[n] = m
            print(f"Loaded N={n} model.")
        elif os.path.exists(legacy_path):
            m = load_serialized_model(legacy_path)
            models[n] = m
            print(f"Loaded N={n} model.")
    full_path = "models/full.joblib"
    legacy_full_path = "models/xgb_full.json"
    if os.path.exists(full_path):
        m = load_serialized_model(full_path)
        models["full"] = m
        print("Loaded Full model.")
    elif os.path.exists(legacy_full_path):
        m = load_serialized_model(legacy_full_path)
        models["full"] = m
        print("Loaded Full model.")

class PredictRequest(BaseModel):
    features: list[float]
    flow_display: str = ""
    ground_truth: int = 255
    pkt_count: int = 0
    duration_s: float = 0.0
    is_closed: bool = False

class PredictBatchRequest(BaseModel):
    features_batch: list[list[float]]

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/predict")
def predict(req: PredictRequest):
    global TOTAL_FLOWS, TOTAL_MCP, TOTAL_NOISE, TOTAL_WITH_GT, CORRECT_PREDS
    t0 = time.perf_counter()
    
    feat = req.features
    if len(feat) != 115:
        return {"error": f"Expected 115 features, got {len(feat)}"}
    
    # We dynamically decide which model to use based on the number of non-zero packets
    # In Rust, total_pkts is index 1
    total_pkts = int(feat[1])
    
    # Find the largest threshold model that we can use
    target_n = None
    for n in reversed(THRESHOLDS):
        if total_pkts >= n and n in models:
            target_n = n
            break
            
    if target_n is None:
        return {"label": 0, "proba": [1.0, 0.0]} # Default noise for early packets
            
    model = models[target_n]
    
    if target_n != "full":
        indices = get_feature_indices(target_n)
        x = np.array([feat[i] for i in indices]).reshape(1, -1)
    else:
        x = np.array(feat).reshape(1, -1)

    probas = model.predict_proba(x)[0]
    
    # Classes: 0 is noise, 1-6 are MCP.
    noise_prob = float(probas[0])
    mcp_prob = float(sum(probas[1:]))

    # Handle probability dilution across multiple classes.
    if mcp_prob > noise_prob:
        label = int(np.argmax(probas[1:]) + 1)
    else:
        label = 0
    
    t1 = time.perf_counter()
    latency_ms = (t1 - t0) * 1000
    LATENCY_SAMPLES.append(latency_ms)

    # --- Update Dashboard Stats ---
    if req.flow_display:
        gt = None if req.ground_truth == 255 else req.ground_truth
        
        # Deduplicate
        if req.flow_display in ACTIVE_PREDICTIONS:
            old_label, old_gt = ACTIVE_PREDICTIONS[req.flow_display]
            if old_label >= 1: TOTAL_MCP = max(0, TOTAL_MCP - 1)
            else: TOTAL_NOISE = max(0, TOTAL_NOISE - 1)
            
            if old_gt is not None:
                TOTAL_WITH_GT = max(0, TOTAL_WITH_GT - 1)
                if (old_gt == 0 and old_label == 0) or (old_gt >= 1 and old_label >= 1):
                    CORRECT_PREDS = max(0, CORRECT_PREDS - 1)
        else:
            TOTAL_FLOWS += 1
            
        if label >= 1: TOTAL_MCP += 1
        else: TOTAL_NOISE += 1
        
        if gt is not None:
            TOTAL_WITH_GT += 1
            if (gt == 0 and label == 0) or (gt >= 1 and label >= 1):
                CORRECT_PREDS += 1
                
        if req.is_closed:
            ACTIVE_PREDICTIONS.pop(req.flow_display, None)
        else:
            ACTIVE_PREDICTIONS[req.flow_display] = (label, gt)
            
        # Update recent flows list
        flow_record = FlowRecord(
            flow_display=req.flow_display,
            label=label,
            proba_mcp=mcp_prob,
            proba_noise=noise_prob,
            pkt_count=req.pkt_count,
            duration_s=req.duration_s,
            ground_truth=gt,
            inference_latency=latency_ms
        )
        
        # Remove old entry if exists to put it at the front
        for i, r in enumerate(RECENT_FLOWS):
            if r.flow_display == req.flow_display:
                del RECENT_FLOWS[i]
                break
        RECENT_FLOWS.appendleft(flow_record)
    
    return {
        "label": label,
        "proba": [noise_prob, mcp_prob]
    }

@app.post("/predict_batch")
def predict_batch(req: PredictBatchRequest):
    predictions = [None] * len(req.features_batch)
    groups = {}
    
    for idx, feat in enumerate(req.features_batch):
        if len(feat) != 115:
            predictions[idx] = {"error": f"Expected 115 features, got {len(feat)}"}
            continue
            
        total_pkts = int(feat[1])
        target_n = None
        for n in reversed(THRESHOLDS):
            if total_pkts >= n and n in models:
                target_n = n
                break
                
        if target_n is None:
            predictions[idx] = {"label": 0, "proba": [1.0, 0.0]}
            continue
            
        groups.setdefault(target_n, []).append((idx, feat))
        
    for target_n, items in groups.items():
        indices = [item[0] for item in items]
        feats = [item[1] for item in items]
        
        model = models[target_n]
        if target_n != "full":
            feat_indices = get_feature_indices(target_n)
            x = np.array([[f[i] for i in feat_indices] for f in feats])
        else:
            x = np.array(feats)
            
        probas_batch = model.predict_proba(x)
        
        for i, probas in zip(indices, probas_batch):
            noise_prob = float(probas[0])
            mcp_prob = float(sum(probas[1:]))
            
            if mcp_prob > noise_prob:
                label = int(np.argmax(probas[1:]) + 1)
            else:
                label = 0
                
            predictions[i] = {
                "label": int(label),
                "proba": [noise_prob, mcp_prob]
            }
            
    return {"predictions": predictions}

# --- Dashboard Endpoints ---

@app.get("/api/stats")
def get_stats():
    acc = None
    if TOTAL_WITH_GT > 0:
        acc = (CORRECT_PREDS / TOTAL_WITH_GT) * 100.0
        
    avg_latency = None
    if len(LATENCY_SAMPLES) > 0:
        avg_latency = sum(LATENCY_SAMPLES) / len(LATENCY_SAMPLES)
        
    return {
        "uptime": int(time.time() - START_TIME),
        "total_flows": TOTAL_FLOWS,
        "total_mcp": TOTAL_MCP,
        "total_noise": TOTAL_NOISE,
        "accuracy": acc,
        "avg_latency": avg_latency
    }

@app.get("/api/flows")
def get_flows():
    return list(RECENT_FLOWS)

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def index():
    return FileResponse("static/dashboard.html")
