import re
from dataclasses import dataclass

import anthropic

_SCRIPT_PROMPT = """\
<instructions>
You are a podcast script writer for "{podcast_name}", a show that turns research questions
into engaging two-host conversations.

Hosts:
- Host 1 (Alex): lead researcher; synthesizes findings in clear 2-3 minute segments;
  explains complex ideas without being condescending
- Host 2 (Sam): curious questioner; voices the listener's natural skepticism;
  asks follow-up questions and introduces counterpoints

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


def generate_script(context: str, config: dict) -> list[ScriptLine]:
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
