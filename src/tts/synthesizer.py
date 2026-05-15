import io
import os
import subprocess
import tempfile
import time
from pathlib import Path

from pydub import AudioSegment

from src.script.generator import ScriptLine

_ELEVENLABS_TIMEOUT = 120  # seconds — long segments can take 30-60s to generate
_ELEVENLABS_RETRIES = 3

# ElevenLabs voice settings applied to both hosts for a consistent sound
_ELEVENLABS_VOICE_SETTINGS = {
    "stability": 0.5,        # 0–1; higher = more consistent, less expressive
    "similarity_boost": 0.8, # 0–1; higher = closer to original voice character
    "style": 0.0,            # 0–1; keep low to avoid over-stylisation
    "use_speaker_boost": True,
}


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
    from elevenlabs.types import VoiceSettings

    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"], timeout=_ELEVENLABS_TIMEOUT)

    voices = config.get("tts", {}).get("elevenlabs_voices", {})
    host1_voice = os.environ.get("ELEVENLABS_HOST1_VOICE_ID") or voices.get("host1", "pNInz6obpgDQGcFmaJgB")
    host2_voice = os.environ.get("ELEVENLABS_HOST2_VOICE_ID") or voices.get("host2", "EXAVITQu4vr4xnSDxMaL")

    speed_config = config.get("tts", {}).get("elevenlabs_speed", {})
    host1_speed = float(speed_config.get("host1", 1.0))
    host2_speed = float(speed_config.get("host2", 1.0))

    voice_settings = VoiceSettings(**_ELEVENLABS_VOICE_SETTINGS)

    segments = []
    for i, line in enumerate(script_lines):
        voice_id = host1_voice if line.speaker == 1 else host2_voice
        speed = host1_speed if line.speaker == 1 else host2_speed
        for attempt in range(_ELEVENLABS_RETRIES):
            try:
                audio_bytes = b"".join(
                    client.text_to_speech.convert(
                        text=line.text,
                        voice_id=voice_id,
                        model_id="eleven_multilingual_v2",
                        speed=speed,
                        voice_settings=voice_settings,
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

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write to a temp file, then apply the mastering chain via ffmpeg
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        combined.export(tmp_path, format="mp3")
        _master(tmp_path, str(output_path))
    finally:
        os.unlink(tmp_path)


def _master(input_path: str, output_path: str) -> None:
    """Apply a consistent mastering chain: high-pass filter + EBU R128 loudness normalisation."""
    subprocess.run(
        [
            "ffmpeg", "-y", "-i", input_path,
            "-af", "highpass=f=80,loudnorm=I=-16:TP=-1.5:LRA=11",
            "-ar", "44100",
            output_path,
        ],
        check=True,
        capture_output=True,
    )
