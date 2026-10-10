"""Descriptive paired effects; bootstrap resamples independent blocks only."""
import math
import random
import statistics


def percentile(values, q):
    if not values or not 0 <= q <= 1 or any(not math.isfinite(x) for x in values):
        raise ValueError("Finite nonempty samples and quantile required")
    values = sorted(values)
    position = (len(values) - 1) * q
    lo, hi = math.floor(position), math.ceil(position)
    return values[lo] + (values[hi] - values[lo]) * (position - lo)


def paired_effect(blocks, repetitions=2000, seed=20261010):
    """One already-aggregated (baseline, CC) pair per independent block."""
    if len(blocks) < 2 or repetitions < 100:
        raise ValueError("Insufficient blocks or bootstrap draws")
    if any(len(pair) != 2 or any(not math.isfinite(x) for x in pair) for pair in blocks):
        raise ValueError("Malformed paired block")
    differences = [on - off for off, on in blocks]
    baseline = statistics.mean(off for off, _ in blocks)
    rng = random.Random(seed)
    draws = [statistics.mean(rng.choices(differences, k=len(blocks))) for _ in range(repetitions)]
    effect = statistics.mean(differences)
    return {"independent_blocks": len(blocks), "absolute_difference": effect,
            "relative_difference_percent": 100 * effect / baseline if baseline else None,
            "absolute_difference_bootstrap_95": [percentile(draws, .025), percentile(draws, .975)],
            "bootstrap_seed": seed, "bootstrap_draws": repetitions,
            "zero_denominator_policy": "relative effect undefined, never infinity"}


def first_detection(records, budget):
    if budget < 1 or len(records) > budget:
        raise ValueError("Invalid candidate budget")
    first = next((i + 1 for i, row in enumerate(records) if row["detected"]), None)
    return {"candidates_to_detection": first, "event_observed": first is not None,
            "censor_candidate": len(records) if first is None else None,
            "budget": budget, "completed_budget": len(records) == budget}
