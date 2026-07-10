"""Deterministic overfit and out-of-sample diagnostics."""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any, Iterable, Sequence


@dataclass(frozen=True)
class WalkForwardSplit:
    train: tuple[int, ...]
    test: tuple[int, ...]
    purged: tuple[int, ...]
    embargoed: tuple[int, ...]


def purged_walk_forward_splits(
    observations: int,
    *,
    train_size: int,
    test_size: int,
    purge: int = 0,
    embargo: int = 0,
    anchored: bool = True,
) -> list[WalkForwardSplit]:
    if min(observations, train_size, test_size) <= 0 or purge < 0 or embargo < 0:
        raise ValueError("split sizes must be positive and purge/embargo non-negative")
    splits = []
    cursor = train_size
    while cursor + purge + test_size <= observations:
        train_start = 0 if anchored else cursor - train_size
        train = tuple(range(train_start, cursor))
        test_start = cursor + purge
        test = tuple(range(test_start, test_start + test_size))
        purged = tuple(range(cursor, test_start))
        embargo_end = min(observations, test_start + test_size + embargo)
        embargoed = tuple(range(test_start + test_size, embargo_end))
        splits.append(WalkForwardSplit(train, test, purged, embargoed))
        cursor = test_start + test_size + embargo
    if not splits:
        raise ValueError("no walk-forward split fits the requested sample")
    return splits


def _array(values: Sequence[float]) -> Any:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("robustness statistics require the 'research' extra") from exc
    result = np.asarray(values, dtype=float)
    if result.ndim != 1 or len(result) < 2 or not np.all(np.isfinite(result)):
        raise ValueError("returns must be a finite one-dimensional sample with at least two values")
    return result


def probabilistic_sharpe_ratio(returns: Sequence[float], *, benchmark_sharpe: float = 0.0) -> float:
    from scipy.stats import kurtosis, norm, skew

    sample = _array(returns)
    volatility = float(sample.std(ddof=1))
    if volatility == 0:
        return 1.0 if float(sample.mean()) > benchmark_sharpe else 0.0
    sharpe = float(sample.mean() / volatility)
    sample_skew = float(skew(sample, bias=False)) if len(sample) > 2 else 0.0
    sample_kurtosis = float(kurtosis(sample, fisher=False, bias=False)) if len(sample) > 3 else 3.0
    variance = 1 - sample_skew * sharpe + ((sample_kurtosis - 1) / 4) * sharpe**2
    if variance <= 0 or not math.isfinite(variance):
        raise ValueError("PSR denominator is not finite and positive")
    score = (sharpe - benchmark_sharpe) * math.sqrt(len(sample) - 1) / math.sqrt(variance)
    return min(1.0, max(0.0, float(norm.cdf(score))))


def deflated_sharpe_ratio(
    returns: Sequence[float],
    *,
    trial_sharpes: Sequence[float],
) -> float:
    from scipy.stats import norm

    trials = _array(trial_sharpes)
    count = len(trials)
    if count < 2:
        raise ValueError("DSR requires at least two tried variants")
    trial_std = float(trials.std(ddof=1))
    euler_gamma = 0.5772156649015329
    expected_max = trial_std * (
        (1 - euler_gamma) * float(norm.ppf(1 - 1 / count))
        + euler_gamma * float(norm.ppf(1 - 1 / (count * math.e)))
    )
    return probabilistic_sharpe_ratio(returns, benchmark_sharpe=expected_max)


def cscv_pbo(performance: Sequence[Sequence[float]], *, blocks: int = 8) -> dict[str, Any]:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("CSCV requires the 'research' extra") from exc
    matrix = np.asarray(performance, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] < 2 or matrix.shape[0] < blocks:
        raise ValueError("performance must have observations x at least two variants and enough rows")
    if blocks < 4 or blocks % 2:
        raise ValueError("CSCV blocks must be an even number of at least four")
    if not np.all(np.isfinite(matrix)):
        raise ValueError("performance matrix must be finite")
    partitions = np.array_split(np.arange(matrix.shape[0]), blocks)
    logits = []
    selected = []
    half = blocks // 2
    for train_blocks in itertools.combinations(range(blocks), half):
        train_set = set(train_blocks)
        train_index = np.concatenate([partitions[index] for index in train_blocks])
        test_index = np.concatenate([partitions[index] for index in range(blocks) if index not in train_set])
        train_scores = matrix[train_index].mean(axis=0)
        winner = int(np.argmax(train_scores))
        test_scores = matrix[test_index].mean(axis=0)
        order = np.argsort(test_scores)
        rank = int(np.where(order == winner)[0][0]) + 1
        relative_rank = rank / (matrix.shape[1] + 1)
        logits.append(math.log(relative_rank / (1 - relative_rank)))
        selected.append(winner)
    pbo = sum(value <= 0 for value in logits) / len(logits)
    return {
        "pbo": float(pbo),
        "combinations": len(logits),
        "logits": logits,
        "selected_variants": selected,
    }


def block_bootstrap_means(
    values: Sequence[float],
    *,
    block_size: int,
    samples: int,
    seed: int,
) -> list[float]:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("bootstrap requires the 'research' extra") from exc
    data = _array(values)
    if block_size <= 0 or block_size > len(data) or samples <= 0:
        raise ValueError("invalid bootstrap block_size or sample count")
    generator = np.random.default_rng(seed)
    means = []
    for _ in range(samples):
        draw = []
        while len(draw) < len(data):
            start = int(generator.integers(0, len(data) - block_size + 1))
            draw.extend(data[start : start + block_size])
        means.append(float(np.mean(draw[: len(data)])))
    return means


def regime_statistics(values: Sequence[float], regimes: Sequence[str]) -> dict[str, dict[str, float]]:
    if len(values) != len(regimes) or not values:
        raise ValueError("values and regimes must be non-empty and aligned")
    groups: dict[str, list[float]] = {}
    for value, regime in zip(values, regimes):
        if not math.isfinite(float(value)):
            raise ValueError("regime values must be finite")
        groups.setdefault(str(regime), []).append(float(value))
    return {
        regime: {
            "observations": float(len(sample)),
            "mean": sum(sample) / len(sample),
            "win_rate": sum(value > 0 for value in sample) / len(sample),
        }
        for regime, sample in sorted(groups.items())
    }


def reality_check(
    performance: Sequence[Sequence[float]],
    *,
    bootstrap_samples: int = 500,
    seed: int = 7,
) -> dict[str, float]:
    try:
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("Reality Check requires the 'research' extra") from exc
    matrix = np.asarray(performance, dtype=float)
    if matrix.ndim != 2 or matrix.shape[1] < 2 or not np.all(np.isfinite(matrix)):
        raise ValueError("performance must be a finite observations x variants matrix")
    observed_means = matrix.mean(axis=0)
    observed_max = float(observed_means.max())
    centered = matrix - observed_means
    standard_errors = matrix.std(axis=0, ddof=1) / math.sqrt(matrix.shape[0])
    observed_spa = float(max((observed_means[index] / standard_errors[index] for index in range(matrix.shape[1]) if standard_errors[index] > 0), default=0.0))
    generator = np.random.default_rng(seed)
    maxima = []
    spa_maxima = []
    for _ in range(bootstrap_samples):
        indexes = generator.integers(0, matrix.shape[0], size=matrix.shape[0])
        sample_means = centered[indexes].mean(axis=0)
        maxima.append(float(sample_means.max()))
        spa_maxima.append(float(max((sample_means[index] / standard_errors[index] for index in range(matrix.shape[1]) if standard_errors[index] > 0), default=0.0)))
    reality_p = (1 + sum(value >= observed_max for value in maxima)) / (bootstrap_samples + 1)
    spa_p = (1 + sum(value >= observed_spa for value in spa_maxima)) / (bootstrap_samples + 1)
    return {"reality_check_pvalue": float(reality_p), "spa_pvalue": float(spa_p)}


def sensitivity_report(
    results: Iterable[dict[str, Any]],
    *,
    parameter: str,
    metric: str,
    selected_value: float,
) -> dict[str, Any]:
    rows = sorted((row for row in results if parameter in row and metric in row), key=lambda row: float(row[parameter]))
    selected = next((row for row in rows if float(row[parameter]) == selected_value), None)
    if selected is None or len(rows) < 2:
        raise ValueError("sensitivity requires selected and neighboring parameter results")
    selected_index = rows.index(selected)
    neighbors = rows[max(0, selected_index - 1) : selected_index] + rows[selected_index + 1 : selected_index + 2]
    selected_metric = float(selected[metric])
    degradations = [selected_metric - float(row[metric]) for row in neighbors]
    return {
        "parameter": parameter,
        "selected_value": selected_value,
        "selected_metric": selected_metric,
        "neighbors": neighbors,
        "max_neighbor_degradation": max(degradations, default=0.0),
    }
