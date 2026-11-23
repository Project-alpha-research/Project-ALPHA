"""The sentence that says how an ML run split its days (light imports; the web reads it)."""

from __future__ import annotations


def split_sentence(folds: list[dict[str, str]]) -> str:
    """Say how often the model was refit and that no model saw its own test days."""
    first, last = folds[0], folds[-1]
    return (
        f"The model was refit {len(folds)} times, each time on days before its own test days. "
        f"First model: trained {first['train_start']} to {first['train_end']}, "
        f"tested {first['test_start']} to {first['test_end']}. "
        f"Last model: trained {last['train_start']} to {last['train_end']}, "
        f"tested {last['test_start']} to {last['test_end']}. "
        "No model saw its own test days."
    )
