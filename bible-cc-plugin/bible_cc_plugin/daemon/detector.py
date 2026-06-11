"""LLM-based key moment detection using Anthropic API."""

from __future__ import annotations

import json
import logging

from ..config import BibleCCConfig

logger = logging.getLogger(__name__)

_DETECTION_PROMPT = """You are analyzing a conversation between a user and an AI agent.
Identify if any KEY MOMENTS occurred in these recent turns.

Key moment types:
- SESSION_START: the user defines the topic or scope of work
- DECISION: the user confirms a choice, approach, or design direction
- ACCOMPLISHMENT: something was completed, verified, and accepted by the user

Do NOT flag:
- Intermediate bug fixes or error corrections
- Exploratory discoveries (unless user explicitly confirms importance)

Respond with a JSON array. If no key moments found, return an empty array [].
Each moment: {"type": "<type>", "title": "<one-line summary>", "narrative": "<2-4 sentences>", "turn_range": "<e.g. 3-7>"}

Conversation turns:
{turns_text}
"""


class MomentDetector:
    def __init__(self, config: BibleCCConfig) -> None:
        self._model = config.detection_model
        self._max_tokens = config.detection_max_tokens
        self._temperature = config.detection_temperature

    def detect(self, session_id: str, turns: list[dict]) -> list[dict]:
        if not turns:
            return []

        turns_text = _format_turns(turns)
        prompt = _DETECTION_PROMPT.replace("{turns_text}", turns_text)

        try:
            import anthropic
            client = anthropic.Anthropic()
            response = client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                temperature=self._temperature,
                system="You are a conversation analyst. Return only valid JSON arrays.",
                messages=[{"role": "user", "content": prompt}],
            )
            text = response.content[0].text
            return _parse_moments(text)
        except Exception as exc:
            logger.warning("moment detection failed for %s: %s", session_id, exc)
            return []


def _format_turns(turns: list[dict]) -> str:
    lines = []
    for i, t in enumerate(turns):
        role = t.get("role", "unknown")
        content = t.get("content", "")[:800]
        lines.append(f"[{i + 1}] {role}: {content}")
    return "\n".join(lines)


def _parse_moments(text: str) -> list[dict]:
    text = text.strip()
    if "```" in text:
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    try:
        result = json.loads(text)
        if isinstance(result, list):
            return [m for m in result if isinstance(m, dict) and "type" in m and "title" in m and "narrative" in m]
    except json.JSONDecodeError:
        pass
    return []
