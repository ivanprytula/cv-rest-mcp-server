"""`CVReviewService`: the extract -> critique orchestration.

Fakes both `CVExtractionService`/`CVCriticService` at the same
`messages.create` boundary as `test_cv_extraction.py`/`test_critic_agent.py`
— what's under test here is the two-call sequence and message-passing, not
either model call in isolation.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

from services.portfolio.cv_extraction import CVExtractionService
from services.portfolio.cv_review.critic_agent import CVCriticService
from services.portfolio.cv_review.review_service import CVReviewService


def _tool_use_response(tool_name: str, input_data: dict):
    block = SimpleNamespace(type="tool_use", name=tool_name, input=input_data)
    return SimpleNamespace(content=[block])


async def test_run_extracts_then_critiques_in_sequence():
    extraction_client = SimpleNamespace(
        messages=SimpleNamespace(
            create=AsyncMock(
                return_value=_tool_use_response("record_cv", {"name": "Ada Lovelace"})
            )
        )
    )
    critic_client = SimpleNamespace(
        messages=SimpleNamespace(
            create=AsyncMock(
                return_value=_tool_use_response(
                    "record_critique", {"concerns": [], "confidence": "high"}
                )
            )
        )
    )
    service = CVReviewService(
        CVExtractionService(extraction_client), CVCriticService(critic_client)
    )

    result = await service.run("Ada Lovelace, mathematician...")

    assert result.draft["name"] == "Ada Lovelace"
    assert result.critique.confidence == "high"
    assert result.critique.concerns == []

    # The critic's call must have received both the resume text and the
    # extractor's draft, in that order — not just the raw resume text.
    critic_call_kwargs = critic_client.messages.create.call_args.kwargs
    critic_prompt = critic_call_kwargs["messages"][0]["content"]
    assert "Ada Lovelace, mathematician" in critic_prompt
    assert '"name": "Ada Lovelace"' in critic_prompt
