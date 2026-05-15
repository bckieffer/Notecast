import io
import os
import time
from pathlib import Path

from pydub import AudioSegment
from pydub.effects import normalize

from src.script.generator import ScriptLine

_ELEVENLABS_TIMEOUT = 120  # seconds — long segments can take 30-60s to generate
_ELEVENLABS_RETRIES = 3


def synthesize(script_lines: list[ScriptLine], config: dict, output_path: Path) -> None:
    provider = config.get("tts", {}).get("provider", "openai")

    if provider == "elevenlabs":
        segments = _synthesize_elevenlabs(script_lines, config)
    else:
        segments = _synthesize_openai(script_lines, config)

    _assemble(segments, script_lines, output_path, config)


def _synthesize_openai(script_lines: list[ScriptLine], config: dict) -> list[AudioSegment]:
    from openai import OpenAI
    client = OpenAI()

    voices = config.get("tts", {}).get("openai_voices", {})
    host1_voice = voices.get("host1", "onyx")
    host2_voice = voices.get("host2", "nova")

    segments = []
    for line in script_lines:
        voice = host1_voice if line.speaker == 1 else host2_voice
        response = client.audio.speech.create(
            model="tts-1-hd",
            voice=voice,
            input=line.text,
        )
        segments.append(AudioSegment.from_file(io.BytesIO(response.content), format="mp3"))

    return segments


def _synthesize_elevenlabs(script_lines: list[ScriptLine], config: dict) -> list[AudioSegment]:
    from elevenlabs import ElevenLabs
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"], timeout=_ELEVENLABS_TIMEOUT)

    host1_voice = os.environ.get("ELEVENLABS_HOST1_VOICE_ID", "pNInz6obpgDQGcFmaJgB")  # Adam
    host2_voice = os.environ.get("ELEVENLABS_HOST2_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")  # Bella

    segments = []
    for i, line in enumerate(script_lines):
        voice_id = host1_voice if line.speaker == 1 else host2_voice
        for attempt in range(_ELEVENLABS_RETRIES):
            try:
                audio_bytes = b"".join(
                    client.text_to_speech.convert(
                        text=line.text,
                        voice_id=voice_id,
                        model_id="eleven_multilingual_v2",
                    )
                )
                break
            except Exception as e:
                if attempt == _ELEVENLABS_RETRIES - 1:
                    raise
                wait = 2 ** attempt
                print(f"  [retry {attempt + 1}/{_ELEVENLABS_RETRIES - 1}] segment {i + 1} failed ({e}), retrying in {wait}s…")
                time.sleep(wait)
        segments.append(AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3"))

    return segments


def _assemble(
    segments: list[AudioSegment],
    script_lines: list[ScriptLine],
    output_path: Path,
    config: dict,
) -> None:
    pause_ms = config.get("tts", {}).get("pause_ms", 200)
    silence = AudioSegment.silent(duration=pause_ms)

    combined = AudioSegment.empty()
    for i, seg in enumerate(segments):
        combined += seg
        if i < len(segments) - 1:
            combined += silence

    combined = normalize(combined)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    combined.export(str(output_path), format="mp3")
