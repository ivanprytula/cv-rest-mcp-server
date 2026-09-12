"""A2A face over the existing `CVExtractionService` — no extraction logic here.

The agent *is* a protocol face on the service Phase 3b already shipped:
`CVExtractionService.extract()` stays exactly as it is, called unchanged.
"""

from __future__ import annotations

import json

from services.portfolio.cv_extraction import CVExtractionService
from services.portfolio.cv_review.a2a import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Message,
    Part,
    Role,
)


def extractor_agent_card(*, url: str) -> AgentCard:
    return AgentCard(
        name="CV Extractor",
        description="Extracts structured CV data from raw resume text.",
        supported_interfaces=[AgentInterface(url=url)],
        version="0.1.0",
        capabilities=AgentCapabilities(),
        skills=[
            AgentSkill(
                id="extract-cv",
                name="Extract CV",
                description="Extracts structured CV fields from resume text.",
                tags=["cv", "extraction"],
            )
        ],
    )


def make_extractor_handler(extraction: CVExtractionService):
    """Build the A2A `SendMessage` handler for the extractor agent.

    The incoming `Message`'s first `text` part is the resume text; the
    reply's first `text` part is the extracted `CVData` dict, JSON-encoded
    (A2A's `Part` has a `data` variant for structured content, but the
    critic agent already expects a string to embed in its own prompt, so
    `text` keeps both agents' `Part` handling identical).
    """

    async def handler(message: Message) -> Message:
        resume_text = next(
            (part.text for part in message.parts if part.text is not None), ""
        )
        draft = await extraction.extract(resume_text)
        return Message(
            message_id=f"{message.message_id}-extracted",
            role=Role.AGENT,
            parts=[Part(text=json.dumps(draft))],
            context_id=message.context_id,
        )

    return handler
