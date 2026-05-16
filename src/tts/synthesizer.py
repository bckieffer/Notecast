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

# ElevenLabs voice settings applied to both hosts for a consistent sound.
# speed is per-host and read from config; remaining settings are shared.
_ELEVENLABS_VOICE_SETTINGS_BASE = {
    "stability": 0.5,        # 0–1; higher = more consistent, less expressive
    "similarity_boost": 0.8, # 0–1; higher = closer to original voice character
    "style": 0.0,            # 0–1; keep low to avoid over-stylisation
    "use_speaker_boost": True,
}


def synthesize(
    script_lines: list[ScriptLine],
    config: dict,
    output_path: Path,
    cache_dir: Path | None = None,
) -> None:
    provider = config.get("tts", {}).get("provider", "openai")

    # Synthesize only spoken lines (skip intro_end sentinel)
    spoken = [l for l in script_lines if l.speaker != 0]

    if cache_dir:
        cache_dir.mkdir(parents=True, exist_ok=True)

    if provider == "elevenlabs":
        segments = _synthesize_elevenlabs(spoken, config, cache_dir)
    else:
        segments = _synthesize_openai(spoken, config, cache_dir)

    _assemble(segments, script_lines, output_path, config)


def _synthesize_openai(
    script_lines: list[ScriptLine],
    config: dict,
    cache_dir: Path | None = None,
) -> list[AudioSegment]:
    from openai import OpenAI
    client = OpenAI()

    voices = config.get("tts", {}).get("openai_voices", {})
    host1_voice = voices.get("host1", "onyx")
    host2_voice = voices.get("host2", "nova")

    speed_config = config.get("tts", {}).get("openai_speed", {})
    host1_speed = float(speed_config.get("host1", 1.0))
    host2_speed = float(speed_config.get("host2", 1.0))

    segments = []
    for i, line in enumerate(script_lines):
        seg_path = cache_dir / f"segment_{i:04d}.mp3" if cache_dir else None
        if seg_path and seg_path.exists():
            print(f"  [cache] segment {i + 1}/{len(script_lines)}")
            segments.append(AudioSegment.from_mp3(str(seg_path)))
            continue

        voice = host1_voice if line.speaker == 1 else host2_voice
        speed = host1_speed if line.speaker == 1 else host2_speed
        response = client.audio.speech.create(
            model="tts-1-hd",
            voice=voice,
            input=line.text,
            speed=speed,
        )
        seg = AudioSegment.from_file(io.BytesIO(response.read()), format="mp3")
        if seg_path:
            seg.export(str(seg_path), format="mp3")
        segments.append(seg)

    return segments


def _synthesize_elevenlabs(
    script_lines: list[ScriptLine],
    config: dict,
    cache_dir: Path | None = None,
) -> list[AudioSegment]:
    from elevenlabs import ElevenLabs
    from elevenlabs.types import VoiceSettings

    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"], timeout=_ELEVENLABS_TIMEOUT)

    voices = config.get("tts", {}).get("elevenlabs_voices", {})
    host1_voice = os.environ.get("ELEVENLABS_HOST1_VOICE_ID") or voices.get("host1", "pNInz6obpgDQGcFmaJgB")
    host2_voice = os.environ.get("ELEVENLABS_HOST2_VOICE_ID") or voices.get("host2", "EXAVITQu4vr4xnSDxMaL")

    speed_config = config.get("tts", {}).get("elevenlabs_speed", {})
    host1_settings = VoiceSettings(**_ELEVENLABS_VOICE_SETTINGS_BASE, speed=float(speed_config.get("host1", 1.0)))
    host2_settings = VoiceSettings(**_ELEVENLABS_VOICE_SETTINGS_BASE, speed=float(speed_config.get("host2", 1.0)))

    segments = []
    for i, line in enumerate(script_lines):
        seg_path = cache_dir / f"segment_{i:04d}.mp3" if cache_dir else None
        if seg_path and seg_path.exists():
            print(f"  [cache] segment {i + 1}/{len(script_lines)}")
            segments.append(AudioSegment.from_mp3(str(seg_path)))
            continue

        voice_id = host1_voice if line.speaker == 1 else host2_voice
        voice_settings = host1_settings if line.speaker == 1 else host2_settings
        for attempt in range(_ELEVENLABS_RETRIES):
            try:
                audio_bytes = b"".join(
                    client.text_to_speech.convert(
                        text=line.text,
                        voice_id=voice_id,
                        model_id="eleven_multilingual_v2",
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

        seg = AudioSegment.from_file(io.BytesIO(audio_bytes), format="mp3")
        if seg_path:
            seg.export(str(seg_path), format="mp3")
        segments.append(seg)

    return segments


def _assemble(
    segments: list[AudioSegment],
    script_lines: list[ScriptLine],  # includes intro_end sentinel
    output_path: Path,
    config: dict,
) -> None:
    pause_ms = config.get("tts", {}).get("pause_ms", 200)
    silence = AudioSegment.silent(duration=pause_ms)

    # Find how many spoken lines precede the intro_end sentinel
    intro_count = 0
    for line in script_lines:
        if line.speaker == 0:
            break
        intro_count += 1

    def build_audio(segs):
        audio = AudioSegment.empty()
        for i, seg in enumerate(segs):
            audio += seg
            if i < len(segs) - 1:
                audio += silence
        return audio

    music_cfg = config.get("intro_music", {})
    music_path = music_cfg.get("path", "assets/intro.mp3")

    has_intro = intro_count < len(segments) and Path(music_path).exists()

    if has_intro:
        intro_audio = build_audio(segments[:intro_count])
        episode_audio = build_audio(segments[intro_count:])
        combined = _mix_intro_music(intro_audio, episode_audio, music_cfg)
    else:
        combined = build_audio(segments)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        combined.export(tmp_path, format="mp3")
        _master(tmp_path, str(output_path))
    finally:
        os.unlink(tmp_path)


def _mix_intro_music(
    intro_audio: AudioSegment,
    episode_audio: AudioSegment,
    cfg: dict,
) -> AudioSegment:
    overlap_ms = cfg.get("overlap_ms", 2000)   # music fades in under last N ms of intro
    sting_ms = cfg.get("sting_ms", 4000)        # music plays solo after intro ends
    fade_in_ms = cfg.get("fade_in_ms", 1500)    # music fade-in duration
    fade_out_ms = cfg.get("fade_out_ms", 2000)  # music fade-out duration
    duck_db = cfg.get("duck_db", 14)            # dB reduction while speech is playing

    music = AudioSegment.from_mp3(cfg.get("path", "assets/intro.mp3"))

    # Trim or loop music to the required length
    needed_ms = overlap_ms + sting_ms + fade_out_ms
    if len(music) < needed_ms:
        loops = (needed_ms // len(music)) + 2
        music = music * loops
    music = music[:needed_ms]

    # Volume envelope:
    # - overlap: fade in from silence, ducked under speech
    # - crossfade: overlay of ducked-fadeout + full-fadein to smoothly rise to full volume
    # - sting: full volume, music plays solo
    # - fade out: ducked level fading to silence under episode speech
    crossfade_ms = min(500, overlap_ms)
    overlap_section = (music[:overlap_ms - crossfade_ms].fade_in(min(fade_in_ms, max(1, overlap_ms - crossfade_ms)))) - duck_db
    xfade_seg = music[overlap_ms - crossfade_ms:overlap_ms]
    crossfade_section = (xfade_seg - duck_db).fade_out(crossfade_ms).overlay(xfade_seg.fade_in(crossfade_ms))
    sting_section = music[overlap_ms:overlap_ms + sting_ms]
    fadeout_section = (music[overlap_ms + sting_ms:] - duck_db).fade_out(fade_out_ms)
    music_track = overlap_section + crossfade_section + sting_section + fadeout_section

    # Speech track: intro + silence gap for the sting + episode
    full_speech = intro_audio + AudioSegment.silent(duration=sting_ms) + episode_audio

    # Overlay music so it starts overlap_ms before intro ends
    music_start = max(0, len(intro_audio) - overlap_ms)
    return full_speech.overlay(music_track, position=music_start)


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
