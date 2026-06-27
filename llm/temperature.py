def escalate(base_temperature: float, attempt: int, step: float = 0.2, cap: float = 0.9) -> float:
    """Raise sampling temperature on later retry attempts.

    Testing showed a model can land on a bad answer and then repeat it
    identically on every retry if temperature stays fixed -- the retry loop
    only has a real chance to land on something different if there's some
    growing randomness to escape the bad attractor.
    """
    return min(base_temperature + (attempt - 1) * step, cap)
