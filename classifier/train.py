import pandas as pd
import numpy as np
import joblib
import os
from time import perf_counter
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score
from sklearn.inspection import permutation_importance
from sklearn.ensemble import ExtraTreesClassifier, HistGradientBoostingClassifier, RandomForestClassifier

try:
    import xgboost as xgb
except ImportError:
    xgb = None

THRESHOLDS = [3, 5, 8, 10, 15, 20]
MODEL_DIR = "models"
REPORT_DIR = os.path.join(MODEL_DIR, "reports")
DATASET_PATH = "../dataset.csv"

def get_features_for_n(n):
    """Return the exact list of feature columns available at packet N."""
    features = ["entropy"]
    for i in range(n):
        features.append(f"seq_size_{i:02d}")
        features.append(f"seq_dir_{i:02d}")
        features.append(f"seq_iat_{i:02d}")
    return features


def build_model_candidates(random_state: int = 42):
    """Return a small set of strong tabular classifiers to compare on validation data."""
    candidates = {
        "extra_trees": ExtraTreesClassifier(
            n_estimators=400,
            random_state=random_state,
            n_jobs=-1,
            class_weight="balanced_subsample",
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=400,
            random_state=random_state,
            n_jobs=-1,
            class_weight="balanced_subsample",
        ),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_iter=250,
            learning_rate=0.08,
            max_depth=6,
            random_state=random_state,
        ),
    }

    if xgb is not None:
        candidates["xgboost"] = xgb.XGBClassifier(
            objective="multi:softprob",
            num_class=7,
            eval_metric="mlogloss",
            max_depth=5,
            learning_rate=0.1,
            n_estimators=300,
            subsample=0.9,
            colsample_bytree=0.9,
            reg_lambda=1.0,
            tree_method="hist",
            random_state=random_state,
        )

    return candidates


def score_model(model, X, y):
    preds = model.predict(X)
    return {
        "accuracy": accuracy_score(y, preds),
        "macro_f1": f1_score(y, preds, average="macro"),
    }


def get_feature_importance(model, X_ref, y_ref):
    """Return a per-feature importance vector for any supported model."""
    if hasattr(model, "feature_importances_"):
        return np.asarray(model.feature_importances_, dtype=float)

    # Fallback for models without native importances.
    perm = permutation_importance(
        model,
        X_ref,
        y_ref,
        scoring="f1_macro",
        n_repeats=5,
        random_state=42,
        n_jobs=-1,
    )
    return np.asarray(perm.importances_mean, dtype=float)


def write_model_report(report_name, model_name, model, X_eval, y_eval, feature_names):
    preds = model.predict(X_eval)
    labels = list(range(7))
    cm = confusion_matrix(y_eval, preds, labels=labels)

    print(f"\nConfusion matrix for {report_name} ({model_name}):")
    print(cm)

    cm_path = os.path.join(REPORT_DIR, f"{report_name}_confusion_matrix.csv")
    cm_df = pd.DataFrame(cm, index=[f"true_{i}" for i in labels], columns=[f"pred_{i}" for i in labels])
    cm_df.to_csv(cm_path, index=True)
    print(f"Saved confusion matrix to {cm_path}")

    importances = get_feature_importance(model, X_eval, y_eval)
    feat_df = pd.DataFrame(
        {
            "feature": feature_names,
            "importance": importances,
        }
    ).sort_values("importance", ascending=False)

    top_k = min(15, len(feat_df))
    print(f"Top {top_k} features for {report_name} ({model_name}):")
    for _, row in feat_df.head(top_k).iterrows():
        print(f"- {row['feature']}: {row['importance']:.6f}")

    feat_path = os.path.join(REPORT_DIR, f"{report_name}_feature_importance.csv")
    feat_df.to_csv(feat_path, index=False)
    print(f"Saved feature importance to {feat_path}")


def train_best_model(X_train, y_train, X_val, y_val):
    best_name = None
    best_model = None
    best_score = -1.0
    comparison_rows = []

    for name, model in build_model_candidates().items():
        print(f"Training candidate model: {name}")
        start_time = perf_counter()
        model.fit(X_train, y_train)
        fit_seconds = perf_counter() - start_time
        metrics = score_model(model, X_val, y_val)
        comparison_rows.append((name, fit_seconds, metrics["accuracy"], metrics["macro_f1"]))
        print(
            f"Validation metrics for {name}: "
            f"accuracy={metrics['accuracy'] * 100:.2f}%, "
            f"macro_f1={metrics['macro_f1'] * 100:.2f}%, "
            f"fit_time={fit_seconds:.2f}s"
        )
        if metrics["macro_f1"] > best_score:
            best_name = name
            best_model = model
            best_score = metrics["macro_f1"]

    print("\nComparison summary (validation set):")
    for name, fit_seconds, accuracy, macro_f1 in comparison_rows:
        print(
            f"- {name}: accuracy={accuracy * 100:.2f}%, "
            f"macro_f1={macro_f1 * 100:.2f}%, fit_time={fit_seconds:.2f}s"
        )

    return best_name, best_model, best_score

def train_early_classifiers():
    if not os.path.exists(DATASET_PATH):
        print(f"Dataset not found at {DATASET_PATH}. Please run generate_dataset.sh first.")
        # Create a dummy dataset for testing the script if it doesn't exist
        print("Creating a dummy dataset to verify compilation...")
        df = pd.DataFrame(np.random.rand(100, 105), columns=[
            "duration_s", "total_pkts", "total_bytes", "pkts_up", "mean_pkt_sz",
            "std_pkt_sz", "min_pkt_sz", "max_pkt_sz", "mean_pkt_sz_up", "std_iat",
            "mean_iat_up", "std_iat_up", "std_iat_down", "byte_ratio_up", "pkt_ratio_up",
            "entropy"
        ] + [f"seq_size_{i:02d}" for i in range(20)] +
            [f"seq_dir_{i:02d}" for i in range(20)] +
            [f"seq_iat_{i:02d}" for i in range(20)] +
            [f"tls_up_{i:02d}" for i in range(3, 20)] +
            [f"tls_down_{i:02d}" for i in range(8, 20)])
        df["label"] = np.random.randint(0, 7, 100)
    else:
        df = pd.read_csv(DATASET_PATH)

    os.makedirs(MODEL_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)

    # Label Map: 0=noise, 1=fetch, 2=memory, 3=filesystem, 4=github, 5=exa, 6=tavily
    y = df["label"].values

    for n in THRESHOLDS:
        print(f"\n--- Training Early Classifier N={n} ---")
        features = get_features_for_n(n)
        X = df[features].values

        X_train, X_temp, y_train, y_temp = train_test_split(
            X,
            y,
            test_size=0.3,
            random_state=42,
            stratify=y,
        )
        X_val, X_test, y_val, y_test = train_test_split(
            X_temp,
            y_temp,
            test_size=0.5,
            random_state=42,
            stratify=y_temp,
        )

        model_name, model, _ = train_best_model(X_train, y_train, X_val, y_val)

        preds = model.predict(X_test)
        acc = accuracy_score(y_test, preds)
        print(f"Selected model for N={n}: {model_name}")
        print(f"Test accuracy at N={n}: {acc*100:.2f}%")

        model_path = os.path.join(MODEL_DIR, f"n{n}.joblib")
        joblib.dump(model, model_path)
        print(f"Saved model to {model_path}")

        write_model_report(
            report_name=f"n{n}",
            model_name=model_name,
            model=model,
            X_eval=X_test,
            y_eval=y_test,
            feature_names=features,
        )

    # Train Full Flow Classifier
    print(f"\n--- Training Full Flow Classifier ---")
    all_features = [c for c in df.columns if c not in ["flow_display", "label"]]
    X = df[all_features].values
    X_train, X_temp, y_train, y_temp = train_test_split(
        X,
        y,
        test_size=0.3,
        random_state=42,
        stratify=y,
    )
    X_val, X_test, y_val, y_test = train_test_split(
        X_temp,
        y_temp,
        test_size=0.5,
        random_state=42,
        stratify=y_temp,
    )
    model_name, model, _ = train_best_model(X_train, y_train, X_val, y_val)
    acc = accuracy_score(y_test, model.predict(X_test))
    print(f"Selected model for full classifier: {model_name}")
    print(f"Full Classifier Accuracy: {acc*100:.2f}%")
    joblib.dump(model, os.path.join(MODEL_DIR, "full.joblib"))
    write_model_report(
        report_name="full",
        model_name=model_name,
        model=model,
        X_eval=X_test,
        y_eval=y_test,
        feature_names=all_features,
    )

if __name__ == "__main__":
    train_early_classifiers()
