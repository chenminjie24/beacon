"""Risk checker implementations for the agent."""

from __future__ import annotations

from qmt_agent.models import RiskChecker, RiskDecision
from relay.domain.models import PulledTask


class AllowAllRiskChecker(RiskChecker):
    def check(self, task: PulledTask, now) -> RiskDecision:
        return RiskDecision(ok=True)
