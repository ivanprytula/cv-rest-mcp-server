"""Orchestrates the extractor and critic agents for one CV review.

Calls both handlers in-process — same-process A2A message exchange, not
two separate HTTP round-trips. Both agents can live in the same Cloud Run
service for now (per ADR-024/Phase 3f plan); splitting into separate
deployments is a valid future step, deferred until there's a real reason
(independent scaling, independent deploys), not built speculatively.
"""

from __future__ import annotations

import json
import uuid

from pydantic import BaseModel

from services.portfolio.cv_extraction import CVExtractionService
from services.portfolio.cv_review.a2a import Message, Part, Role
from services.portfolio.cv_review.critic_agent import Critique, CVCriticService
from services.portfolio.cv_review.critic_agent_a2a import make_critic_handler
from services.portfolio.cv_review.extractor_agent import make_extractor_handler


class CVReviewResult(BaseModel):
    """The extractor's draft plus the critic's pass over it, for the human."""

    draft: dict
    critique: Critique


class CVReviewService:
    """Runs extract -> critique as one call, both steps A2A message exchanges."""

    def __init__(
        self, extraction: CVExtractionService, critic: CVCriticService
    ) -> None:
        self._extract = make_extractor_handler(extraction)
        self._critique = make_critic_handler(critic)

    async def run(self, resume_text: str) -> CVReviewResult:
        request_id = uuid.uuid4().hex
        extract_reply = await self._extract(
            Message(
                message_id=f"{request_id}-extract",
                role=Role.USER,
                parts=[Part(text=resume_text)],
            )
        )
        draft_json = next(
            part.text for part in extract_reply.parts if part.text is not None
        )

        critique_reply = await self._critique(
            Message(
                message_id=f"{request_id}-critique",
                role=Role.USER,
                parts=[Part(text=resume_text), Part(text=draft_json)],
            )
        )
        critique_json = next(
            part.text for part in critique_reply.parts if part.text is not None
        )

        return CVReviewResult(
            draft=json.loads(draft_json),
            critique=Critique.model_validate_json(critique_json),
        )
