"""
ML Model Training.

Trains classifiers on the per-flow feature CSV produced by the feature
extraction module.  Three classifiers are evaluated:
  - Random Forest
  - XGBoost (with Gradient Boosting fallback if xgboost is not installed)
  - Logistic Regression (baseline)

The best model (by F1-score on the test set) is saved as a pickle file.

Usage:
    python -m model.train
    python -m model.train --features data/features.csv --output models/
"""

import argparse
import logging
import os
import pickle
import warnings
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    ConfusionMatrixDisplay,
    classification_report,
    confusion_matrix,
    f1_score,
)
from sklearn.model_selection import StratifiedKFold, cross_val_score, train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.pipeline import Pipeline

warnings.filterwarnings("ignore")

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# Features to drop before training (identifiers, not predictive)
_DROP_COLS = ["src_ip", "dst_ip", "label"]


def load_and_prepare(csv_path: str) -> tuple[pd.DataFrame, pd.Series, LabelEncoder]:
    """Load CSV, drop identifier columns, encode labels."""
    df = pd.read_csv(csv_path)
    if "label" not in df.columns:
        raise ValueError("CSV must contain a 'label' column")

    le = LabelEncoder()
    y = le.fit_transform(df["label"])
    X = df.drop(columns=[c for c in _DROP_COLS if c in df.columns])

    # Fill any NaN with column median
    X = X.fillna(X.median(numeric_only=True))

    logger.info(
        "Dataset: %d samples, %d features, classes=%s",
        len(df),
        X.shape[1],
        list(le.classes_),
    )
    return X, pd.Series(y), le


def _build_classifiers() -> dict:
    """Return a dict of classifier name -> sklearn-compatible estimator."""
    classifiers = {}

    classifiers["Random Forest"] = RandomForestClassifier(
        n_estimators=200,
        max_depth=None,
        min_samples_leaf=2,
        n_jobs=-1,
        random_state=42,
    )

    try:
        from xgboost import XGBClassifier
        classifiers["XGBoost"] = XGBClassifier(
            n_estimators=200,
            max_depth=6,
            learning_rate=0.1,
            use_label_encoder=False,
            eval_metric="logloss",
            random_state=42,
            n_jobs=-1,
        )
        logger.info("XGBoost available — including it in the comparison.")
    except ImportError:
        logger.info("XGBoost not installed — using Gradient Boosting instead.")
        classifiers["Gradient Boosting"] = GradientBoostingClassifier(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.1,
            random_state=42,
        )

    classifiers["Logistic Regression"] = Pipeline([
        ("scaler", StandardScaler()),
        # StandardScaler is required here: Logistic Regression converges poorly
        # on unscaled data with features spanning many orders of magnitude.
        # Tree-based models (RF, XGBoost) are scale-invariant so no scaler is
        # needed for them.
        ("clf", LogisticRegression(max_iter=1000, random_state=42)),
    ])

    return classifiers


def train(
    csv_path: str = "data/features.csv",
    output_dir: str = "models",
    test_size: float = 0.2,
    cv_folds: int = 5,
) -> str:
    """
    Train all classifiers, print evaluation metrics, and save the best model.

    Returns the path to the saved model file.
    """
    X, y, le = load_and_prepare(csv_path)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=42, stratify=y
    )
    logger.info("Train size: %d  Test size: %d", len(X_train), len(X_test))

    classifiers = _build_classifiers()
    results: dict[str, dict] = {}

    print("\n" + "=" * 70)
    print("TRAINING AND EVALUATION")
    print("=" * 70)

    for name, clf in classifiers.items():
        print(f"\n--- {name} ---")

        # Cross-validation on training set
        cv = StratifiedKFold(n_splits=cv_folds, shuffle=True, random_state=42)
        cv_scores = cross_val_score(clf, X_train, y_train, cv=cv, scoring="f1_weighted", n_jobs=-1)
        print(f"  CV F1 (mean ± std): {cv_scores.mean():.4f} ± {cv_scores.std():.4f}")

        # Full train + test
        clf.fit(X_train, y_train)
        y_pred = clf.predict(X_test)
        test_f1 = f1_score(y_test, y_pred, average="weighted")
        print(f"  Test F1 (weighted): {test_f1:.4f}")
        print(classification_report(y_test, y_pred, target_names=le.classes_))

        cm = confusion_matrix(y_test, y_pred)
        print("  Confusion matrix:")
        print(cm)

        results[name] = {"model": clf, "test_f1": test_f1, "cv_mean": cv_scores.mean()}

    # Pick best model
    best_name = max(results, key=lambda n: results[n]["test_f1"])
    best_model = results[best_name]["model"]
    best_f1 = results[best_name]["test_f1"]

    print("\n" + "=" * 70)
    print(f"BEST MODEL: {best_name}  (test F1 = {best_f1:.4f})")
    print("=" * 70)

    # Feature importance (if available)
    raw_clf = best_model.named_steps["clf"] if hasattr(best_model, "named_steps") else best_model
    if hasattr(raw_clf, "feature_importances_"):
        fi = pd.Series(raw_clf.feature_importances_, index=X.columns)
        top10 = fi.nlargest(10)
        print("\nTop-10 feature importances:")
        print(top10.to_string())

    # Save
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    model_path = str(Path(output_dir) / "best_model.pkl")
    with open(model_path, "wb") as f:
        pickle.dump({"model": best_model, "label_encoder": le, "feature_names": list(X.columns)}, f)
    logger.info("Best model saved to %s", model_path)
    return model_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Train MCP traffic classifiers")
    parser.add_argument(
        "--features", default="data/features.csv", help="Path to the features CSV file"
    )
    parser.add_argument(
        "--output", default="models", help="Directory to save the best model"
    )
    parser.add_argument(
        "--test-size", type=float, default=0.2, help="Fraction of data for the test set"
    )
    parser.add_argument("--cv-folds", type=int, default=5, help="Number of cross-validation folds")
    args = parser.parse_args()

    train(args.features, args.output, args.test_size, args.cv_folds)


if __name__ == "__main__":
    main()
