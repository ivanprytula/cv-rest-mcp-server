"""A2A face over `CVCriticService` — no critique logic here.

Named `critic_agent_a2a` rather than folding into `critic_agent.py`: that
module is the domain service (Anthropic call, schema, error type), this is
its protocol face, same split as `extractor_agent.py`/`cv_extraction.py`.
"""

from __future__ import annotations

import json

from services.portfolio.cv_review.a2a import (
    AgentCapabilities,
    AgentCard,
    AgentInterface,
    AgentSkill,
    Message,
    Part,
    Role,
)
from services.portfolio.cv_review.critic_agent import CVCriticService


def critic_agent_card(*, url: str) -> AgentCard:
    return AgentCard(
        name="CV Critic",
        description="Reviews a CV extraction against its source resume text.",
        supported_interfaces=[AgentInterface(url=url)],
        version="0.1.0",
        capabilities=AgentCapabilities(),
        skills=[
            AgentSkill(
                id="critique-cv-extraction",
                name="Critique CV Extraction",
                description="Flags likely misses or hallucinations in an extraction.",
                tags=["cv", "review"],
            )
        ],
    )


def make_critic_handler(critic: CVCriticService):
    """Build the A2A `SendMessage` handler for the critic agent.

    Expects two `text` parts on the incoming `Message`: the original resume
    text, then the extractor's JSON-encoded draft (the order
    `CVReviewService` sends them in). The reply's `text` part is the
    JSON-encoded `Critique`.
    """

    async def handler(message: Message) -> Message:
        texts = [part.text for part in message.parts if part.text is not None]
        resume_text = texts[0] if texts else ""
        extracted_draft = json.loads(texts[1]) if len(texts) > 1 else {}

        critique = await critic.critique(
            resume_text=resume_text, extracted_draft=extracted_draft
        )
        return Message(
            message_id=f"{message.message_id}-critiqued",
            role=Role.AGENT,
            parts=[Part(text=critique.model_dump_json())],
            context_id=message.context_id,
        )

    return handler
