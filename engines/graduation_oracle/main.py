"""
PumpDesk v2 — Graduation Oracle (Engine)
Predicts the probability that a PumpFun token will graduate (hit 100% curve).

Phase 1 (now): Heuristic model using:
  - Current curve_pct and velocity
  - Holder count and growth rate
  - Creator score from creator_judge
  - Social hype score from social_aggregator
  - Time since creation

Phase 2 (later): Train an actual ML model on our historical data
once we have enough trades from the sniper and copier running.

Publishes INTEL_GRAD_PROBABILITY for orchestrator confidence boosting.
"""

import asyncio
import json
import logging
import time
import sys

sys.path.insert(0, "/app")

from shared.redis_bus import RedisBus, Channels
from shared.models import utcnow
from shared.config import STATE_DIR

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-8s [%(name)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("pumpdesk.oracle")
bus = RedisBus("graduation_oracle")

# Cache of token features for prediction
token_features: dict = {}  # mint -> {curve_pct, velocity, holders, creator_score, hype, age}


def predict_graduation(features: dict) -> float:
    """Heuristic graduation probability (0.0-1.0)."""
    prob = 0.0

    curve = features.get("curve_pct", 0)
    velocity = features.get("velocity", 0)
    holders = features.get("holders", 0)
    creator_score = features.get("creator_score", 0.5)
    hype = features.get("hype_score", 0)
    age_min = features.get("age_minutes", 0)

    # Curve position is the strongest predictor
    if curve >= 0.95: prob += 0.50
    elif curve >= 0.85: prob += 0.30
    elif curve >= 0.70: prob += 0.15
    elif curve >= 0.50: prob += 0.05

    # Velocity — fast-filling curves are more likely to complete
    if velocity > 0.02: prob += 0.15
    elif velocity > 0.005: prob += 0.08

    # Holders — more unique buyers = more organic
    if holders > 100: prob += 0.10
    elif holders > 30: prob += 0.05

    # Creator reputation
    if creator_score > 0.7: prob += 0.10
    elif creator_score < 0.3: prob -= 0.15

    # Social hype
    if hype > 0.6: prob += 0.10
    elif hype > 0.3: prob += 0.05

    # Age penalty — old tokens that haven't graduated are less likely to
    if age_min > 120 and curve < 0.80:
        prob -= 0.10
    if age_min > 60 and curve < 0.50:
        prob -= 0.15

    return max(0.0, min(1.0, prob))


async def handle_curve_signal(channel: str, data: dict):
    """When sniper/momentum reports curve data, predict graduation."""
    token = data.get("token", {})
    mint = token.get("mint", "")
    if not mint:
        return

    features = {
        "curve_pct": token.get("curve_pct", data.get("metadata", {}).get("curve_pct", 0)),
        "velocity": data.get("metadata", {}).get("velocity_pct_per_min", 0),
        "holders": data.get("metadata", {}).get("holders", 0),
        "creator_score": 0.5,  # filled by creator_judge if available
        "hype_score": 0.0,     # filled by social_aggregator if available
        "age_minutes": 0,
    }
    token_features[mint] = features

    prob = predict_graduation(features)
    if prob > 0.3:
        await bus.publish(Channels.INTEL_GRAD_PROB, {
            "mint": mint,
            "symbol": token.get("symbol", ""),
            "probability": round(prob, 3),
            "features": features,
            "timestamp": utcnow(),
        })


async def main():
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    await bus.connect()
    await bus.subscribe(Channels.SIGNAL_CURVE, handle_curve_signal)
    await bus.subscribe(Channels.SIGNAL_MOMENTUM, handle_curve_signal)
    log.info("Graduation Oracle started (heuristic mode)")
    await bus.listen()

if __name__ == "__main__":
    asyncio.run(main())

