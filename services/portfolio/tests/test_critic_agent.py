"""CV critique: the tool-use parsing branch. Same fake-client pattern as
`test_cv_extraction.py` — no real Anthropic call is made."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import anthropic
import pytest

from services.portfolio.cv_review.critic_agent import (
    CVCriticService,
    CVCritiqueError,
    _tool_schema,
)


def _tool_use_response(input_data: dict):
    block = SimpleNamespace(type="tool_use", name="record_critique", input=input_data)
    return SimpleNamespace(content=[block])


def test_tool_schema_forbids_extra_top_level_keys():
    assert _tool_schema()["input_schema"]["additionalProperties"] is False


class TestCritique:
    async def test_returns_a_validated_critique(self):
        client = SimpleNamespace(
            messages=SimpleNamespace(
                create=AsyncMock(
                    return_value=_tool_use_response(
                        {"concerns": ["title looks invented"], "confidence": "low"}
                    )
                )
            )
        )
        service = CVCriticService(client)

        critique = await service.critique(
            resume_text="Ada Lovelace, mathematician...",
            extracted_draft={"name": "Ada Lovelace", "title": "CTO"},
        )

        assert critique.concerns == ["title looks invented"]
        assert critique.confidence == "low"

    async def test_empty_concerns_means_nothing_found(self):
        client = SimpleNamespace(
            messages=SimpleNamespace(
                create=AsyncMock(return_value=_tool_use_response({}))
            )
        )
        service = CVCriticService(client)

        critique = await service.critique(
            resume_text="clean resume", extracted_draft={"name": "Ada Lovelace"}
        )

        assert critique.concerns == []
        assert critique.missing_sections == []

    async def test_raises_when_the_model_returns_no_tool_call(self):
        client = SimpleNamespace(
            messages=SimpleNamespace(
                create=AsyncMock(return_value=SimpleNamespace(content=[]))
            )
        )
        service = CVCriticService(client)

        with pytest.raises(CVCritiqueError, match="did not return"):
            await service.critique(resume_text="x", extracted_draft={})

    async def test_wraps_an_api_error(self):
        async def _raise(*args, **kwargs):
            raise anthropic.APIConnectionError(request=AsyncMock())

        client = SimpleNamespace(messages=SimpleNamespace(create=_raise))
        service = CVCriticService(client)

        with pytest.raises(CVCritiqueError, match="critique call failed"):
            await service.critique(resume_text="x", extracted_draft={})
