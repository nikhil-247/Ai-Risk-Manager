import numpy as np
import pandas as pd
import pytest

from ml.train_benchmark import choose_threshold, metrics_for_predictions, validate_dataframe


def test_metrics_have_confusion_matrix_and_cost():
    result = metrics_for_predictions(
        [0, 1, 1, 0], [0.1, 0.8, 0.7, 0.9], 0.5,
        false_positive_cost=5, false_negative_cost=100,
    )
    assert result["confusion_matrix"] == {"tp": 2, "fp": 1, "fn": 0, "tn": 1}
    assert result["precision"] == pytest.approx(2 / 3)
    assert result["recall"] == pytest.approx(1.0)
    assert result["total_misclassification_cost"] == 5


def test_threshold_selection_uses_explicit_costs():
    threshold, cost = choose_threshold(
        [0, 1, 1, 0], [0.1, 0.8, 0.7, 0.9], 5, 100,
    )
    assert 0 <= threshold <= 1
    assert cost <= 5


def test_dataset_validation_rejects_missing_columns():
    with pytest.raises(ValueError, match="missing required columns"):
        validate_dataframe(pd.DataFrame({"Amount": [1] * 120, "Class": [0, 1] * 60}))


def test_dataset_validation_rejects_nan_feature():
    rows = 120
    frame = pd.DataFrame({
        "Time": np.arange(rows), "Amount": np.ones(rows),
        "V1": [0.0] * (rows - 1) + [np.nan],
        "Class": [0, 1] * (rows // 2),
    })
    with pytest.raises(ValueError, match="missing or non-numeric"):
        validate_dataframe(frame)


def test_dataset_validation_returns_features_and_binary_target():
    rows = 120
    frame = pd.DataFrame({
        "Time": np.arange(rows), "Amount": np.ones(rows),
        "V1": np.zeros(rows), "Class": [0, 1] * (rows // 2),
    })
    features, labels = validate_dataframe(frame)
    assert features == ["Time", "Amount", "V1"]
    assert len(labels) == rows
