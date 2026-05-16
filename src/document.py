"""
Document pre-processor.

Reads a local markdown file and uses Claude to extract a research question
and a structured context summary that drives the research agent.
"""

from pathlib import Path

import anthropic

_EXTRACT_PROMPT = """\
<instructions>
You are preparing a research briefing from a document. Read the document below and produce two things:

1. A concise research question (one sentence) that captures the central topic or argument of the document and can drive independent web research to supplement or verify its claims.

2. A structured context summary that extracts:
   - The main thesis or argument
   - Key claims or findings (bullet points)
   - Gaps, open questions, or areas where current research would add value

Return your response as a JSON object with exactly two keys: "question" and "context".
</instructions>

<document>
{content}
</document>

<output_format>
{{"question": "...", "context": "..."}}
</output_format>"""


def load_document(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")


def extract_document_context(content: str, config: dict) -> tuple[str, str]:
    """
    Returns (question, context_summary) derived from the document.
    question — suitable as the research driver
    context_summary — structured key points to inject into the research agent
    """
    import json
    import re

    client = anthropic.Anthropic()
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        messages=[{
            "role": "user",
            "content": _EXTRACT_PROMPT.format(content=content[:12000]),
        }],
    )

    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-z]*\n?", "", raw).rstrip("```").strip()

    data = json.loads(raw)
    return data["question"], data["context"]
