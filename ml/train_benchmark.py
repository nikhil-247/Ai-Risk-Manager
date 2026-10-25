"""Train and evaluate a fraud model on the ULB/Kaggle credit-card benchmark.

Expected input CSV: Time, V1...V28, Amount, Class. Dataset downloads are deliberately
manual; users must review the dataset terms and keep raw financial data out of Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import joblib
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.dummy import DummyClassifier
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    average_precision_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split


def validate_dataframe(frame: pd.DataFrame) -> tuple[list[str], np.ndarray]:
    """Validate schema and return feature names plus binary target without modifying input."""
    required = {"Time", "Amount", "Class"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Dataset is missing required columns: {', '.join(sorted(missing))}")
    if len(frame) < 100:
        raise ValueError("At least 100 rows are required for a meaningful train/validation/test split.")
    labels = pd.to_numeric(frame["Class"], errors="coerce")
    if labels.isna().any() or not set(labels.unique()).issubset({0, 1}):
        raise ValueError("Class must contain only binary labels 0 and 1.")
    features = [column for column in frame.columns if column != "Class"]
    numeric = frame[features].apply(pd.to_numeric, errors="coerce")
    if numeric.isna().any().any():
        raise ValueError("Feature columns contain missing or non-numeric values.")
    if not np.isfinite(numeric.to_numpy(dtype=float)).all():
        raise ValueError("Feature columns contain infinite values.")
    if labels.nunique() != 2:
        raise ValueError("The dataset must contain both legitimate (0) and fraud (1) labels.")
    return features, labels.to_numpy(dtype=int)


def metrics_for_predictions(
    y_true: Sequence[int],
    probabilities: Sequence[float],
    threshold: float,
    false_positive_cost: float = 5.0,
    false_negative_cost: float = 100.0,
) -> dict:
    """Calculate metrics from scores using an explicit, caller-provided threshold."""
    y_true_arr = np.asarray(y_true, dtype=int)
    prob = np.asarray(probabilities, dtype=float)
    if len(y_true_arr) == 0 or len(y_true_arr) != len(prob):
        raise ValueError("y_true and probabilities must be non-empty and have equal length.")
    if not np.isfinite(prob).all() or ((prob < 0) | (prob > 1)).any():
        raise ValueError("probabilities must be finite values between 0 and 1.")
    if not 0 <= threshold <= 1:
        raise ValueError("threshold must be between 0 and 1.")
    predicted = (prob >= threshold).astype(int)
    tn, fp, fn, tp = confusion_matrix(y_true_arr, predicted, labels=[0, 1]).ravel()
    try:
        pr_auc = float(average_precision_score(y_true_arr, prob))
    except ValueError:
        pr_auc = None
    try:
        roc_auc = float(roc_auc_score(y_true_arr, prob))
    except ValueError:
        roc_auc = None
    fp_cost = float(fp * false_positive_cost)
    fn_cost = float(fn * false_negative_cost)
    return {
        "threshold": float(threshold),
        "precision": float(precision_score(y_true_arr, predicted, zero_division=0)),
        "recall": float(recall_score(y_true_arr, predicted, zero_division=0)),
        "f1": float(f1_score(y_true_arr, predicted, zero_division=0)),
        "accuracy": float(accuracy_score(y_true_arr, predicted)),
        "pr_auc": pr_auc,
        "roc_auc": roc_auc,
        "confusion_matrix": {"tp": int(tp), "fp": int(fp), "fn": int(fn), "tn": int(tn)},
        "false_positive_cost_total": fp_cost,
        "false_negative_cost_total": fn_cost,
        "total_misclassification_cost": fp_cost + fn_cost,
    }


def choose_threshold(
    y_true: Sequence[int],
    probabilities: Sequence[float],
    false_positive_cost: float,
    false_negative_cost: float,
) -> tuple[float, float]:
    """Pick the minimum-cost threshold on validation data; never inspect the test labels."""
    candidates = np.unique(np.concatenate([np.linspace(0.01, 0.99, 99), np.asarray(probabilities)]))
    results = [
        (metrics_for_predictions(y_true, probabilities, float(threshold), false_positive_cost, false_negative_cost)[
            "total_misclassification_cost"
        ], float(threshold))
        for threshold in candidates
    ]
    cost, threshold = min(results, key=lambda item: (item[0], -item[1]))
    return threshold, cost


def chronological_split(frame: pd.DataFrame):
    ordered = frame.sort_values("Time", kind="stable").reset_index(drop=True)
    n = len(ordered)
    train_end, validation_end = int(n * 0.60), int(n * 0.80)
    if train_end < 2 or validation_end - train_end < 2 or n - validation_end < 2:
        raise ValueError("Not enough rows to create chronological train/validation/test partitions.")
    return ordered.iloc[:train_end], ordered.iloc[train_end:validation_end], ordered.iloc[validation_end:]


def stratified_split(frame: pd.DataFrame, target: np.ndarray):
    train_val, test = train_test_split(
        frame, test_size=0.20, random_state=42, stratify=target
    )
    train_target = train_val["Class"].astype(int)
    train, validation = train_test_split(
        train_val, test_size=0.25, random_state=42, stratify=train_target
    )
    return train, validation, test


def run_training(args: argparse.Namespace) -> dict:
    data_path = Path(args.data)
    if not data_path.is_file():
        raise FileNotFoundError(
            f"Dataset not found at {data_path}. Download the public creditcard.csv benchmark manually "
            "and pass --data /path/to/creditcard.csv. Raw data is intentionally not bundled."
        )
    frame = pd.read_csv(data_path)
    features, target = validate_dataframe(frame)
    if args.split == "temporal":
        train_frame, val_frame, test_frame = chronological_split(frame)
    else:
        train_frame, val_frame, test_frame = stratified_split(frame, target)

    for name, partition in (("train", train_frame), ("validation", val_frame), ("test", test_frame)):
        if partition["Class"].nunique() != 2:
            raise ValueError(
                f"The {name} partition contains only one class. Try --split stratified or inspect dataset ordering."
            )

    scale_columns = [column for column in ("Time", "Amount") if column in features]
    preprocess = ColumnTransformer(
        [("scale_amount_time", StandardScaler(), scale_columns)],
        remainder="passthrough",
        verbose_feature_names_out=False,
    )
    classifier = RandomForestClassifier(
        n_estimators=args.trees,
        max_depth=args.max_depth,
        min_samples_leaf=2,
        class_weight="balanced_subsample",
        n_jobs=-1,
        random_state=42,
    )
    pipeline = Pipeline([("preprocess", preprocess), ("classifier", classifier)])
    x_train, y_train = train_frame[features], train_frame["Class"].astype(int).to_numpy()
    x_val, y_val = val_frame[features], val_frame["Class"].astype(int).to_numpy()
    x_test, y_test = test_frame[features], test_frame["Class"].astype(int).to_numpy()

    pipeline.fit(x_train, y_train)
    val_prob = pipeline.predict_proba(x_val)[:, 1]
    threshold, validation_cost = choose_threshold(
        y_val, val_prob, args.false_positive_cost, args.false_negative_cost
    )
    test_prob = pipeline.predict_proba(x_test)[:, 1]
    result = metrics_for_predictions(
        y_test, test_prob, threshold, args.false_positive_cost, args.false_negative_cost
    )

    baseline = DummyClassifier(strategy="prior")
    baseline.fit(x_train, y_train)
    baseline_prob = baseline.predict_proba(x_test)[:, 1]
    baseline_result = metrics_for_predictions(
        y_test, baseline_prob, 0.5, args.false_positive_cost, args.false_negative_cost
    )
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    model_path = output / "fraud_pipeline.joblib"
    report_path = output / "benchmark_report.json"
    joblib.dump({
        "pipeline": pipeline,
        "threshold": threshold,
        "features": features,
        "model_name": "RandomForestClassifier",
        "dataset_schema": "ULB credit-card fraud benchmark (Time, V1-V28, Amount, Class)",
    }, model_path)

    raw_hash = hashlib.sha256(data_path.read_bytes()).hexdigest()
    report = {
        "status": "benchmark_evaluated",
        "source": "public_benchmark",
        "dataset": "ULB/Kaggle Credit Card Fraud Detection (creditcard.csv)",
        "dataset_sha256": raw_hash,
        "rows": int(len(frame)),
        "feature_count": len(features),
        "class_prevalence": float(frame["Class"].mean()),
        "split_strategy": args.split,
        "split_rows": {
            "train": int(len(train_frame)), "validation": int(len(val_frame)), "test": int(len(test_frame))
        },
        "model": "RandomForestClassifier(class_weight=balanced_subsample)",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **result,
        "baseline": baseline_result,
        "threshold_selection": {
            "method": "minimum validation misclassification cost",
            "validation_cost": float(validation_cost),
            "false_positive_cost_assumption": float(args.false_positive_cost),
            "false_negative_cost_assumption": float(args.false_negative_cost),
            "cost_units": "user-defined cost units; replace with merchant-approved assumptions",
        },
        "warning": (
            "Metrics are from the held-out partition of the specified public benchmark, not a guarantee of "
            "production performance. Cost values depend on user-supplied assumptions. Check class prevalence, "
            "dataset terms and feature limitations before interpreting or deploying this model."
        ),
        "artifacts": {"model": str(model_path), "report": str(report_path)},
    }
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="data/raw/creditcard.csv", help="Path to creditcard.csv")
    parser.add_argument("--output-dir", default="artifacts", help="Directory for model/report outputs")
    parser.add_argument("--split", choices=("temporal", "stratified"), default="temporal")
    parser.add_argument("--trees", type=int, default=120, help="Number of Random Forest trees")
    parser.add_argument("--max-depth", type=int, default=18)
    parser.add_argument("--false-positive-cost", type=float, default=5.0)
    parser.add_argument("--false-negative-cost", type=float, default=100.0)
    args = parser.parse_args()
    if args.trees < 10 or args.max_depth < 2:
        parser.error("--trees must be >= 10 and --max-depth must be >= 2")
    if args.false_positive_cost < 0 or args.false_negative_cost < 0:
        parser.error("Cost assumptions must be non-negative")
    return args


if __name__ == "__main__":
    report = run_training(parse_args())
    print(json.dumps({
        "status": report["status"],
        "dataset": report["dataset"],
        "threshold": report["threshold"],
        "precision": report["precision"],
        "recall": report["recall"],
        "f1": report["f1"],
        "pr_auc": report["pr_auc"],
        "confusion_matrix": report["confusion_matrix"],
        "total_misclassification_cost": report["total_misclassification_cost"],
        "report_path": report["artifacts"]["report"],
    }, indent=2))
