
"""
FastFlow Early Inference API (Machine Learning Engine)
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
import threading

app = FastAPI(title="FastFlow Early Inference API")

THRESHOLDS = [3, 5, 8, 10, 15, 20]
models = {}

# --- State for Dashboard ---
START_TIME = time.time()
DASH_LOCK = threading.Lock()

class DashboardState:
    def __init__(self):
        self.total_flows = 0
        self.total_mcp = 0
        self.total_noise = 0
        self.total_with_gt = 0
        self.correct_preds = 0
        self.latency_samples = deque(maxlen=1000)
        self.active_predictions = {} # flow_display -> (label, ground_truth, timestamp)
        self.recent_flows = {}       # flow_display -> FlowRecord (ordered by insertion in Python 3.7+)

state = DashboardState()

class FlowRecord(BaseModel):
    flow_display: str
    label: int
    proba_mcp: float
    proba_noise: float
    pkt_count: int
    duration_s: float
    ground_truth: Optional[int] = None
    inference_latency: float

def load_serialized_model(path: str):
    if path.endswith(".joblib"):
        return joblib.load(path)
    import xgboost as xgb
    model = xgb.XGBClassifier()
    model.load_model(path)
    return model

def get_feature_indices(n: int) -> list[int]:
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

def update_stats(flow_display: str, label: int, gt: Optional[int], is_closed: bool, mcp_prob: float, noise_prob: float, pkt_count: int, duration_s: float, latency_ms: float):
    with DASH_LOCK:
        now = time.time()
        
        # ACTIVE_PREDICTIONS Cleanup (prevent memory leaks)
        if len(state.active_predictions) > 2000:
            # Remove flows older than 5 minutes
            stale_keys = [k for k, v in state.active_predictions.items() if now - v[2] > 300]
            for k in stale_keys:
                del state.active_predictions[k]

        if flow_display in state.active_predictions:
            old_label, old_gt, _ = state.active_predictions[flow_display]
            if old_label >= 1: state.total_mcp = max(0, state.total_mcp - 1)
            else: state.total_noise = max(0, state.total_noise - 1)
            
            if old_gt is not None:
                state.total_with_gt = max(0, state.total_with_gt - 1)
                if (old_gt == 0 and old_label == 0) or (old_gt >= 1 and old_label >= 1):
                    state.correct_preds = max(0, state.correct_preds - 1)
        else:
            state.total_flows += 1
            
        if label >= 1: state.total_mcp += 1
        else: state.total_noise += 1
        
        if gt is not None:
            state.total_with_gt += 1
            if (gt == 0 and label == 0) or (gt >= 1 and label >= 1):
                state.correct_preds += 1
                
        if is_closed:
            state.active_predictions.pop(flow_display, None)
        else:
            state.active_predictions[flow_display] = (label, gt, now)
            
        # O(1) recent flows dictionary
        # Pop if exists to re-insert at the end (making it most recent in dict order)
        state.recent_flows.pop(flow_display, None)
        state.recent_flows[flow_display] = FlowRecord(
            flow_display=flow_display,
            label=label,
            proba_mcp=mcp_prob,
            proba_noise=noise_prob,
            pkt_count=pkt_count,
            duration_s=duration_s,
            ground_truth=gt,
            inference_latency=latency_ms
        )
        
        # Enforce max length of 500
        if len(state.recent_flows) > 500:
            oldest_key = next(iter(state.recent_flows))
            del state.recent_flows[oldest_key]


@app.post("/predict")
def predict(req: PredictRequest):
    t0 = time.perf_counter()
    
    feat = req.features
    if len(feat) != 115:
        return {"error": f"Expected 115 features, got {len(feat)}"}
    
    total_pkts = int(feat[1])
    
    target_n = None
    for n in reversed(THRESHOLDS):
        if total_pkts >= n and n in models:
            target_n = n
            break
            
    if target_n is None:
        return {"label": 0, "proba": [1.0, 0.0]} 
            
    model = models[target_n]
    
    if target_n != "full":
        indices = get_feature_indices(target_n)
        x = np.array([feat[i] for i in indices]).reshape(1, -1)
    else:
        x = np.array(feat).reshape(1, -1)

    probas = model.predict_proba(x)[0]
    
    noise_prob = float(probas[0])
    mcp_prob = float(sum(probas[1:]))

    if mcp_prob > noise_prob:
        label = int(np.argmax(probas[1:]) + 1)
    else:
        label = 0
    
    t1 = time.perf_counter()
    latency_ms = (t1 - t0) * 1000
    
    with DASH_LOCK:
        state.latency_samples.append(latency_ms)

    if req.flow_display:
        gt = None if req.ground_truth == 255 else req.ground_truth
        update_stats(
            flow_display=req.flow_display,
            label=label,
            gt=gt,
            is_closed=req.is_closed,
            mcp_prob=mcp_prob,
            noise_prob=noise_prob,
            pkt_count=req.pkt_count,
            duration_s=req.duration_s,
            latency_ms=latency_ms
        )
    
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

@app.get("/api/stats")
def get_stats():
    with DASH_LOCK:
        acc = None
        if state.total_with_gt > 0:
            acc = (state.correct_preds / state.total_with_gt) * 100.0
            
        avg_latency = None
        if len(state.latency_samples) > 0:
            avg_latency = sum(state.latency_samples) / len(state.latency_samples)
            
        return {
            "uptime": int(time.time() - START_TIME),
            "total_flows": state.total_flows,
            "total_mcp": state.total_mcp,
            "total_noise": state.total_noise,
            "accuracy": acc,
            "avg_latency": avg_latency
        }

@app.get("/api/flows")
def get_flows():
    with DASH_LOCK:
        # Return most recent flows (end of dict) reversed to match the queue behavior
        return list(reversed(list(state.recent_flows.values())))

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def index():
    return FileResponse("static/dashboard.html")
