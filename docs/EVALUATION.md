# Fraud benchmark evaluation protocol

## Dataset

The training script expects the public ULB/Kaggle Credit Card Fraud Detection CSV named `creditcard.csv`, with columns `Time`, `Amount`, `V1` through `V28`, and binary target `Class`. The repository does not redistribute the raw dataset; obtain it from the dataset's original publisher/host and review its license/terms before use.

Place the file at `data/raw/creditcard.csv`. Do not commit the CSV.

## Reproducible run

Install the optional ML environment:

```bash
pip install -r ml/requirements.txt
python -m ml.train_benchmark --data data/raw/creditcard.csv --split temporal
```

The script creates `artifacts/fraud_pipeline.joblib` and `artifacts/benchmark_report.json`. Both are ignored by Git because the model artifact is generated from data locally. The API reads a valid report artifact and exposes its held-out metrics through `GET /api/evaluation`.

A lower-cost quick iteration can use `--trees 30`, while the default is 120 trees. To compare a stratified holdout, use `--split stratified`; chronological splitting is the default and more directly tests later observations, but can fail with datasets whose tail contains only one class.

## Method

- Target is `Class`; it is explicitly excluded from features.
- Default split is chronological: first 60% train, next 20% validation, final 20% test after sorting by `Time`.
- The scaler is fitted inside a scikit-learn pipeline on training data only.
- Random Forest class weighting handles imbalance without resampling the held-out data.
- The decision threshold is selected against a validation set using user-defined false-positive and false-negative costs.
- Final metrics are computed on the test partition after threshold selection: precision, recall, F1, accuracy, average precision (PR-AUC), ROC-AUC and confusion matrix.
- A most-frequent/prior dummy baseline is reported alongside the trained model.
- Data SHA-256, split counts, threshold and cost assumptions are included in the report.

## Interpret results carefully

Threshold costs default to 5 units for each false positive and 100 units for each false negative. These are example assumptions, not externally validated financial costs. Supply merchant-approved assumptions for meaningful cost analysis. Dataset amounts and labels are not a substitute for real-world prospective validation.

The benchmark uses anonymized PCA features and does not provide the merchant-specific account-age, location-risk or velocity features in the interactive demo form. The benchmark model is therefore an offline evaluation artifact in this phase; the dashboard's custom transaction scorer remains a separately labelled demo rules engine. Do not imply the trained benchmark model scores the demo form.

Synthetic sample transactions and their displayed status labels are interface fixtures. Never combine them with benchmark results or claim that they establish real fraud model quality.
