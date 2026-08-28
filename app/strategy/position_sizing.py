from __future__ import annotations

import math


def calculate_contracts(account_equity: float, candidate_max_loss: float, risk_fraction: float) -> int:
    if account_equity <= 0 or candidate_max_loss <= 0 or not 0 < risk_fraction <= 1:
        return 0
    allowed_risk = account_equity * risk_fraction
    return math.floor(allowed_risk / candidate_max_loss)
