"""Retrieval and extraction evaluation metrics.

Implements:
- slot_fill_f1: Field-level precision/recall for extraction accuracy
- entity_accuracy: Exact-match accuracy on specific typed fields
- clarification_efficiency: How many turns to reach completeness
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ExtractionMetrics:
    """Results of a slot-fill evaluation run."""

    precision: float
    recall: float
    f1: float
    field_accuracy: dict[str, float]  # per-field accuracy


def slot_fill_f1(
    predicted: dict[str, Any],
    expected: dict[str, Any],
    tolerance: float = 0.0,
) -> ExtractionMetrics:
    """Compute precision, recall and F1 for slot filling.

    Args:
        predicted: Fields extracted by the agent.
        expected: Ground-truth fields from the golden dataset.
        tolerance: Fractional tolerance for numeric fields (e.g. 0.05 = 5%).

    Returns:
        ExtractionMetrics with precision, recall, F1 and per-field accuracy.
    """
    true_pos = 0
    false_pos = 0
    false_neg = 0
    field_acc: dict[str, float] = {}

    all_keys = set(predicted) | set(expected)
    for key in all_keys:
        pred_val = predicted.get(key)
        exp_val = expected.get(key)

        if exp_val is None and pred_val is None:
            continue
        if exp_val is None:
            false_pos += 1
            field_acc[key] = 0.0
        elif pred_val is None:
            false_neg += 1
            field_acc[key] = 0.0
        else:
            match = _values_match(pred_val, exp_val, tolerance)
            if match:
                true_pos += 1
                field_acc[key] = 1.0
            else:
                false_pos += 1
                false_neg += 1
                field_acc[key] = 0.0

    precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) else 0.0
    recall = true_pos / (true_pos + false_neg) if (true_pos + false_neg) else 0.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0

    return ExtractionMetrics(
        precision=round(precision, 3),
        recall=round(recall, 3),
        f1=round(f1, 3),
        field_accuracy=field_acc,
    )


def _values_match(pred: Any, exp: Any, tol: float) -> bool:
    # Check if two values match within numeric tolerance.
    if isinstance(exp, (int, float)) and isinstance(pred, (int, float)):
        if exp == 0:
            return pred == 0
        return abs(pred - exp) / abs(exp) <= tol

    # If working with objects/dicts like sleep/exercise
    if isinstance(exp, dict) and isinstance(pred, dict):
        for k in exp:
            if k not in pred or not _values_match(pred[k], exp[k], tol):
                return False
        return True
    elif isinstance(exp, list) and isinstance(pred, list):
        if len(exp) != len(pred):
            return False
        for p_val, e_val in zip(pred, exp):
            if not _values_match(p_val, e_val, tol):
                return False
        return True

    # Unpack enum values for correct string comparison
    if hasattr(pred, "value"):
        pred = pred.value
    if hasattr(exp, "value"):
        exp = exp.value

    return str(pred).lower().strip() == str(exp).lower().strip()
