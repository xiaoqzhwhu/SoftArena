from __future__ import annotations


def compute_score(data_source=None, solution_str=None, ground_truth=None, extra_info=None, **kwargs):
    """Minimal verl-compatible reward hook for SoftArena GRPO smoke runs.

    Production GRPO should replace this with a verifier-backed reward that can
    execute the proposed tool trajectory in an isolated SoftArena environment.
    This MVP hook supports prepared GRPO rows by returning the verifier score
    stored in extra_info or ground_truth.
    """
    if isinstance(extra_info, dict) and "score" in extra_info:
        return float(extra_info["score"])
    if ground_truth is not None:
        try:
            return float(ground_truth)
        except (TypeError, ValueError):
            return 0.0
    return 0.0
