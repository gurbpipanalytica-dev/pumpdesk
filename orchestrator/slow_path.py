"""
PumpDesk v2 — Orchestrator: Slow Path (Claude AI Strategy)
Runs every 2-5 minutes. Not in the trade decision loop.
Adjusts parameters, assesses portfolio health, rebalances capital,
generates strategic insights for the dashboard.
"""

import json
import logging
import time
from datetime import datetime, timezone

from shared.config import ANTHROPIC_API_KEY
from shared.models import utcnow

log = logging.getLogger("pumpdesk.orchestrator.slow_path")

_claude = None


def _get_claude():
    global _claude
    if _claude is not None:
        return _claude
    if not ANTHROPIC_API_KEY:
        log.warning("No ANTHROPIC_API_KEY — slow path disabled")
        return None
    try:
        import anthropic
        _claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        log.info("Claude client ready")
        return _claude
    except Exception as e:
        log.warning(f"Anthropic unavailable: {e}")
        return None


class SlowPath:
    """Claude-powered strategic assessment. Runs periodically, not per-signal."""

    def __init__(self, portfolio_state):
        self.state = portfolio_state
        self.assessment_history = []
        self.interval_seconds = 300  # 5 minutes default

    def run_cycle(self) -> dict:
        """Run one strategic assessment cycle. Returns assessment dict."""
        client = _get_claude()
        if not client:
            return {"status": "ai_offline", "timestamp": utcnow()}

        portfolio_summary = self._build_portfolio_summary()

        system = """You are PumpDesk AI — the strategic brain of a PumpFun trading + token launching operation on Solana.

You manage:
- 4 trading bots: graduation sniper, wallet copier, curve arb, momentum scanner
- 3 creator bots: token launcher, volume bot, anti-sniper trap
- 5 engines: progressive exit, creator judge, social aggregator, graduation oracle, LP farmer

Your job every cycle:
1. Assess portfolio health (exposure, PnL trajectory, risk)
2. Identify which bots should be more/less aggressive
3. Suggest parameter adjustments (confidence thresholds, position sizes, exit stages)
4. Flag any concerns (overexposure to one token, creator risk, market regime change)
5. Spot opportunities the individual bots might miss

Respond ONLY in valid JSON with these keys:
- assessment: string (1-2 sentence summary)
- risk_level: "low" | "medium" | "high" | "critical"
- parameter_adjustments: list of {bot, param, old_value, new_value, reason}
- opportunities: list of {description, suggested_bot, urgency}
- concerns: list of {description, severity, suggested_action}
- market_regime: "bullish" | "neutral" | "bearish" | "volatile"
"""

        user_msg = f"""Current portfolio state:
{json.dumps(portfolio_summary, indent=2)}

Time: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}

Run your assessment."""

        try:
            resp = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=1000,
                system=system,
                messages=[{"role": "user", "content": user_msg}]
            )
            raw = resp.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
            if raw.endswith("```"):
                raw = raw[:-3]
            raw = raw.strip()

            result = json.loads(raw)
            result["timestamp"] = utcnow()
            result["status"] = "ok"

            self.assessment_history.insert(0, result)
            if len(self.assessment_history) > 50:
                self.assessment_history.pop()

            log.info(f"AI assessment: {result.get('assessment', '')[:100]}")
            log.info(f"Risk: {result.get('risk_level')} | Regime: {result.get('market_regime')}")

            return result

        except json.JSONDecodeError as e:
            log.error(f"AI returned invalid JSON: {e}")
            return {"status": "json_error", "timestamp": utcnow()}
        except Exception as e:
            err_str = str(e).lower()
            if any(k in err_str for k in ["credit", "balance", "overloaded", "rate"]):
                log.warning(f"AI temporarily unavailable: {e}")
            else:
                log.error(f"AI cycle error: {e}")
            return {"status": "error", "error": str(e), "timestamp": utcnow()}

    def _build_portfolio_summary(self) -> dict:
        positions = []
        for pos in self.state.open_positions.values():
            positions.append({
                "bot": pos.bot,
                "mint": pos.mint[:12] + "...",
                "size_sol": pos.size_sol,
                "entry": pos.entry_price_sol,
                "current": pos.current_price_sol,
                "pnl": pos.unrealized_pnl_sol,
                "status": pos.status,
                "exit_stages_remaining": len(pos.exit_stages_remaining),
            })

        return {
            "open_positions": positions,
            "position_count": len(positions),
            "total_exposure_sol": self.state.total_exposure_sol,
            "daily_pnl_sol": self.state.daily_pnl_sol,
            "daily_trades": self.state.daily_trades,
            "daily_loss_sol": self.state.daily_loss_sol,
            "paper_mode": True,  # from config
            "creator_scores_cached": len(self.state.creator_scores),
            "hype_scores_cached": len(self.state.hype_scores),
            "blacklisted_creators": len(self.state.blacklisted_creators),
        }

    def get_latest_assessment(self) -> dict:
        if self.assessment_history:
            return self.assessment_history[0]
        return {"status": "no_assessment_yet"}

