from pydantic import BaseModel, Field, field_validator


class ScoreRequest(BaseModel):
    amount: float = Field(ge=0, le=1_000_000_000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    country: str = Field(default="US", min_length=2, max_length=2)
    cross_border: bool = False
    transactions_last_hour: int = Field(default=1, ge=0, le=100_000)
    account_age_days: int = Field(default=365, ge=0, le=100_000)
    hour_of_day: int = Field(default=12, ge=0, le=23)

    @field_validator("currency", "country")
    @classmethod
    def uppercase_codes(cls, value: str) -> str:
        return value.upper()


def score_features(payload: ScoreRequest, low_max: int = 29, review_max: int = 64) -> dict:
    """Transparent demo rules. Not trained, calibrated or intended for real payment decisions."""
    points = 0
    reasons: list[str] = []
    if payload.amount >= 2000:
        points += 25
        reasons.append("High transaction amount")
    elif payload.amount >= 750:
        points += 12
        reasons.append("Elevated transaction amount")
    if payload.transactions_last_hour >= 8:
        points += 28
        reasons.append("High transaction velocity")
    elif payload.transactions_last_hour >= 4:
        points += 14
        reasons.append("Elevated transaction velocity")
    if payload.account_age_days < 7:
        points += 22
        reasons.append("Very new account")
    elif payload.account_age_days < 30:
        points += 10
        reasons.append("Recently created account")
    if payload.hour_of_day <= 4:
        points += 10
        reasons.append("Unusual hour (demo rule)")
    if payload.cross_border:
        points += 15
        reasons.append("Cross-border transaction")

    score = min(points, 100)
    if score <= low_max:
        category, action = "low", "allow_for_review_policy"
    elif score <= review_max:
        category, action = "medium", "manual_review"
    else:
        category, action = "high", "priority_review"
    return {
        "risk_score": score,
        "risk_category": category,
        "recommended_action": action,
        "reasons": reasons or ["No configured demo risk rule was triggered"],
        "score_type": "heuristic_demo_score",
        "disclaimer": "This is a transparent demo heuristic, not a calibrated fraud probability.",
    }
