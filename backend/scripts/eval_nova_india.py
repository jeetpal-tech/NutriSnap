"""
eval_nova_india.py - Evaluate the NOVA model on Indian Open Food Facts products.

Spec: ARCHITECTURE §7.5.
Run in Google Colab (streams the parquet; do not download the full dataset).

Usage (Colab):
    !python eval_nova_india.py

Metrics: accuracy, macro-F1, per-class precision/recall, confusion matrix,
reliability table (10 bins), majority baseline, gate fallback rate.
"""
# M3 / post-spike will implement the full evaluation.
# Stub: explains the intended approach.

print(
    "eval_nova_india.py: stub — implement after the spike confirms the pooling method.\n"
    "See ARCHITECTURE §7.5 for the full spec (DuckDB over HF parquet, India filter)."
)
