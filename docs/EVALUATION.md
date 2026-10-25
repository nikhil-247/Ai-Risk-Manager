# Evaluation policy

The initial dashboard uses hand-authored synthetic examples to exercise charts and review workflows. The API exposes illustrative metrics to test the evaluation interface. These numbers are not a performance claim.

For a defensible model report:

- Identify the dataset, version, license and label definition.
- Split data before resampling, scaling decisions that could leak labels, or model selection.
- Fit all preprocessing on training data only.
- Keep final test data held out until model and threshold selection are finished.
- Report class prevalence, confusion matrix, precision, recall, F1, PR-AUC and a baseline.
- Explain threshold choice and quantify operational cost using explicit assumptions.
- Document data limitations, feature semantics and reproducibility commands.
- Do not describe a risk score as a probability unless it has been calibrated and validated for that purpose.
