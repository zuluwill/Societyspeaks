"""Statistical primitives shared by statement-level results and the consensus engine."""
import math

# 95% CI by default; change via WILSON_Z if a different level is required.
WILSON_Z = 1.959963984540054  # norm.ppf(0.975)


def wilson_interval(successes, n, z=WILSON_Z):
    """
    Wilson score confidence interval for a binomial proportion.

    More accurate than the normal approximation at small n and at extreme
    proportions, and never produces impossible bounds (e.g. negative or
    >1 probabilities). See Wilson (1927).

    Args:
        successes: number of "yes" outcomes
        n: total trials (must be >= 0)
        z: z-score for the desired confidence level (default 1.96 → 95%)

    Returns:
        (point_estimate, lower_bound, upper_bound) as floats in [0, 1].
        For n=0 returns (0.0, 0.0, 1.0) — the maximally-uncertain prior.
    """
    n = int(n)
    if n <= 0:
        return 0.0, 0.0, 1.0
    k = int(successes)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / denom
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denom
    return float(p), float(max(0.0, centre - margin)), float(min(1.0, centre + margin))
