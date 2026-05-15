import re
from dataclasses import dataclass

import anthropic

_SCRIPT_PROMPT = """\
<instructions>
You are a podcast script writer for "{podcast_name}", a show that turns research questions
into engaging two-host conversations.

Hosts:
- Host 1 (Alex): lead researcher; presents findings confidently in short, direct sentences;
  keeps momentum — no restating what was just said, no throat-clearing phrases like "so what
  this means is" or "basically"; uses minimal verbal fillers; drives the narrative forward
- Host 2 (Sam): the listener's proxy; mostly encounters this topic fresh and asks the questions
  a curious, intelligent person would naturally wonder — "wait, but why?", "hold on, what does
  that actually mean?", "so what's the practical implication of that?"; occasionally reveals
  partial prior knowledge and uses it to push back — "I thought X was the case, doesn't that
  contradict what you're saying?" or "I've heard the opposite argument that..."; reacts with
  genuine surprise or skepticism when findings are counterintuitive; never asks questions they
  already know the answer to; never lectures or summarizes

Rules:
- Format EVERY spoken line as <host1>text</host1> or <host2>text</host2> — no other text
- Include natural verbal fillers ("right", "exactly", "you know", "huh") for realism
- Open with a hook that references the original question
- Close with a brief summary and 1-2 open questions for future episodes
- Target length: {word_count} words of dialogue
- Tone: informative and engaging — never dry, never oversimplified
</instructions>

<background_information>
{context}
</background_information>

<output_format>
<host1>Opening hook...</host1>
<host2>Response...</host2>
(continue alternating for the full episode)
</output_format>"""


@dataclass
class ScriptLine:
    speaker: int   # 1 = Host 1, 2 = Host 2
    text: str


_DESCRIPTION_PROMPT = """\
Write a 2-3 sentence podcast episode description for "{podcast_name}".

The episode explores this question: {question}

Key findings from the research:
{brief}

Rules:
- Start with "In this episode," or a similar hook
- Write in present tense, as if describing what listeners will hear
- Be specific — name at least one concrete finding or insight from the research
- Do not use markdown, headers, or bullet points — plain prose only
- Maximum 60 words"""


def generate_episode_description(question: str, brief: str, config: dict) -> str:
    client = anthropic.Anthropic()

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        messages=[{
            "role": "user",
            "content": _DESCRIPTION_PROMPT.format(
                podcast_name=config.get("podcast_name", "Notecast"),
                question=question,
                brief=brief[:2000],
            ),
        }],
    )

    return message.content[0].text.strip()


_FACT_CHECK_PROMPT = """\
<instructions>
You are a fact-checker for a podcast script. Your job is to ensure every factual claim
in the script is supported by the research brief below.

For each line that contains a claim NOT supported by the brief:
- Rewrite that line so the claim is accurate according to the brief, OR
- Remove the unsupported claim and replace it with something the brief does support
- Preserve the speaker's voice, tone, and conversational style
- Do NOT change lines that are already accurate or are opinions/transitions

Return the COMPLETE corrected script in the exact same <host1>/<host2> tag format.
If no corrections are needed, return the script unchanged.
</instructions>

<research_brief>
{brief}
</research_brief>

<script>
{script}
</script>"""


def generate_script(context: str, config: dict, brief: str = "") -> list[ScriptLine]:
    client = anthropic.Anthropic()

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": _SCRIPT_PROMPT.format(
                podcast_name=config.get("podcast_name", "Notecast"),
                word_count=config.get("script", {}).get("word_count", 3000),
                context=context,
            ),
        }],
    )

    lines = _parse_script(message.content[0].text)

    if brief and config.get("script", {}).get("fact_check", True):
        lines = _fact_check_and_rewrite(lines, brief, client)

    return lines


def _fact_check_and_rewrite(lines: list[ScriptLine], brief: str, client) -> list[ScriptLine]:
    script_text = "\n".join(
        f"<host{l.speaker}>{l.text}</host{l.speaker}>" for l in lines
    )

    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8192,
        messages=[{
            "role": "user",
            "content": _FACT_CHECK_PROMPT.format(brief=brief, script=script_text),
        }],
    )

    return _parse_script(message.content[0].text)


def _parse_script(text: str) -> list[ScriptLine]:
    # Collect all tagged lines with their position so ordering is preserved
    lines: list[tuple[int, ScriptLine]] = []

    for tag, speaker in [("host1", 1), ("host2", 2)]:
        for match in re.finditer(rf"<{tag}>(.*?)</{tag}>", text, re.DOTALL):
            lines.append((match.start(), ScriptLine(speaker=speaker, text=match.group(1).strip())))

    lines.sort(key=lambda x: x[0])
    result = [line for _, line in lines]

    if not result:
        raise ValueError("Script parsing failed — no <host1>/<host2> tags found in Claude response")

    host1 = sum(1 for l in result if l.speaker == 1)
    host2 = sum(1 for l in result if l.speaker == 2)
    if host1 == 0 or host2 == 0:
        raise ValueError(f"Malformed script: host1={host1} lines, host2={host2} lines")

    word_count = sum(len(l.text.split()) for l in result)
    if word_count < 500:
        raise ValueError(f"Script too short: {word_count} words")

    return result
