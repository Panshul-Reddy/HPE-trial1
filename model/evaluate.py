"""
ML Model Evaluation.

Loads a previously trained model and evaluates it on new data (a CSV
produced by the feature extraction module).

Usage:
    python -m model.evaluate --model models/best_model.pkl --features data/features.csv
    python -m model.evaluate --model models/best_model.pkl --features data/new_features.csv
"""

import argparse
import logging
import pickle
import sys
from pathlib import Path

import pandas as pd
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix, f1_score, precision_score, recall_score

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

_DROP_COLS = ["src_ip", "dst_ip", "src_port", "dst_port", "protocol", "label"]


def load_model(model_path: str) -> tuple:
    """Load the model bundle saved by train.py.  Returns (model, label_encoder, feature_names)."""
    with open(model_path, "rb") as f:
        bundle = pickle.load(f)
    return bundle["model"], bundle["label_encoder"], bundle["feature_names"]


def evaluate(model_path: str, features_csv: str) -> None:
    """Evaluate the saved model on a features CSV and print metrics."""
    model, le, feature_names = load_model(model_path)

    df = pd.read_csv(features_csv)
    if "label" not in df.columns:
        logger.error("Features CSV must contain a 'label' column for evaluation.")
        sys.exit(1)

    y_true = le.transform(df["label"])
    X = df.drop(columns=[c for c in _DROP_COLS if c in df.columns])

    # Align columns to what was seen at training time
    missing = [c for c in feature_names if c not in X.columns]
    if missing:
        logger.warning("Missing features (filling with 0): %s", missing)
        for c in missing:
            X[c] = 0
    X = X[feature_names]
    X = X.fillna(X.median(numeric_only=True))

    y_pred = model.predict(X)

    acc = accuracy_score(y_true, y_pred)
    prec = precision_score(y_true, y_pred, average="weighted")
    rec = recall_score(y_true, y_pred, average="weighted")
    f1 = f1_score(y_true, y_pred, average="weighted")
    misclassified = (y_true != y_pred).sum()

    print("\n" + "=" * 60)
    print(f"Evaluation on: {features_csv}")
    print(f"Model:         {model_path}")
    print("=" * 60)
    print(f"\n  Accuracy:      {acc:.4f}  ({acc*100:.1f}%)")
    print(f"  Precision:     {prec:.4f}")
    print(f"  Recall:        {rec:.4f}")
    print(f"  F1-score:      {f1:.4f}")
    print(f"  Misclassified: {misclassified} / {len(y_true)}")
    print("\nClassification Report:")
    print(classification_report(y_true, y_pred, target_names=le.classes_))
    print("Confusion Matrix:")
    print(confusion_matrix(y_true, y_pred))

    # Per-sample predictions with probabilities (if available)
    if hasattr(model, "predict_proba"):
        proba = model.predict_proba(X)
        out_df = df[["src_ip", "dst_ip", "src_port", "dst_port", "label"]].copy()
        out_df["predicted_label"] = le.inverse_transform(y_pred)
        for i, cls in enumerate(le.classes_):
            out_df[f"prob_{cls}"] = proba[:, i]
        pred_csv = str(Path(features_csv).with_suffix("")) + "_predictions.csv"
        out_df.to_csv(pred_csv, index=False)
        logger.info("Per-flow predictions saved to %s", pred_csv)


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate MCP traffic classifier")
    parser.add_argument(
        "--model",
        default="models/best_model.pkl",
        help="Path to the saved model pickle file",
    )
    parser.add_argument(
        "--features",
        default="data/features.csv",
        help="Path to the features CSV file to evaluate on",
    )
    args = parser.parse_args()

    evaluate(args.model, args.features)


if __name__ == "__main__":
    main()
