"""
Notecast clip generator — creates short-form social video from episode highlights.

Selects the best exchange from a script, aligns it to the audio, generates
HeyGen talking-head video for each speaker turn, and assembles a 9:16 portrait
MP4 with burned-in captions.

Usage:
  python src/clip.py output/audio/episode.mp3 --script output/episodes/001/script.json
  python src/clip.py output/audio/episode.mp3 --script output/episodes/001/script.json --duration 60
  python src/clip.py output/audio/episode.mp3 --script output/episodes/001/script.json --output promo.mp4
"""

import base64
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import anthropic
import httpx
import typer
import yaml
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer(add_completion=False)

_HEYGEN_UPLOAD = "https://upload.heygen.com/v1/asset"
_HEYGEN_GENERATE = "https://api.heygen.com/v2/video/generate"
_HEYGEN_STATUS = "https://api.heygen.com/v1/video_status.get"
_HEYGEN_IDS_CACHE = Path("assets/heygen_ids.json")

_POLL_INTERVAL = 8
_POLL_TIMEOUT = 600


# ── Config / script helpers ───────────────────────────────────────────────────

def _load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _load_script(script_path: Path) -> list:
    from src.script.generator import ScriptLine
    data = json.loads(script_path.read_text())
    return [ScriptLine(speaker=d["speaker"], text=d["text"]) for d in data]


# ── Highlight selection ───────────────────────────────────────────────────────

def _select_highlight(spoken: list, target_seconds: int) -> tuple[int, int]:
    """Claude picks the most engaging continuous exchange of ~target_seconds."""
    script_text = "\n".join(f"[{i}] Host{l.speaker}: {l.text}" for i, l in enumerate(spoken))
    prompt = f"""Select the best ~{target_seconds}-second highlight from this podcast transcript for social media promotion.

{script_text}

Choose a continuous sequence that:
- Contains a surprising insight, clear explanation, or satisfying back-and-forth
- Starts and ends at complete sentence boundaries
- Stands alone without needing context from the rest of the episode
- Avoids generic intro or outro lines

Reply with JSON only: {{"start_idx": <int>, "end_idx": <int>, "reason": "<one sentence>"}}"""

    msg = anthropic.Anthropic().messages.create(
        model="claude-sonnet-4-6",
        max_tokens=128,
        messages=[{"role": "user", "content": prompt}],
    )
    result = json.loads(msg.content[0].text.strip())
    typer.echo(f"  Reason: {result['reason']}")
    return result["start_idx"], result["end_idx"]


# ── Audio timing ─────────────────────────────────────────────────────────────

def _estimate_position(script_lines: list, start_idx: int, end_idx: int, config: dict) -> tuple[float, float]:
    """Estimate the rough start/end time (seconds) of spoken lines start_idx–end_idx."""
    pause_s = config.get("tts", {}).get("pause_ms", 200) / 1000
    sting_s = config.get("intro_music", {}).get("sting_ms", 6000) / 1000
    speed = config.get("tts", {}).get("elevenlabs_speed", {})
    wps = {
        1: 2.5 * float(speed.get("host1", 1.0)),
        2: 2.5 * float(speed.get("host2", 1.0)),
    }

    # Count how many spoken lines precede the intro_end sentinel
    intro_count = sum(1 for l in script_lines[:next(
        (i for i, l in enumerate(script_lines) if l.speaker == 0), len(script_lines)
    )])

    spoken = [l for l in script_lines if l.speaker != 0]
    t = 0.0
    line_starts, line_ends = [], []
    for i, line in enumerate(spoken):
        if i == intro_count:
            t += sting_s
        line_starts.append(t)
        t += len(line.text.split()) / wps.get(line.speaker, 2.5)
        line_ends.append(t)
        if i < len(spoken) - 1:
            t += pause_s

    pad = 30.0
    return max(0.0, line_starts[start_idx] - pad), line_ends[end_idx] + pad


def _ffmpeg_cut(src: Path, start_s: float, end_s: float, dst: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(src),
         "-ss", str(start_s), "-to", str(end_s), "-c", "copy", str(dst)],
        check=True, capture_output=True,
    )


def _forced_alignment(audio_path: Path, text: str) -> list[dict]:
    from elevenlabs import ElevenLabs
    client = ElevenLabs(api_key=os.environ["ELEVENLABS_API_KEY"])
    result = client.forced_alignment.create(file=audio_path.read_bytes(), text=text)
    return [{"text": w.text, "start": float(w.start), "end": float(w.end)} for w in result.words]


# ── Captions ─────────────────────────────────────────────────────────────────

def _srt_ts(s: float) -> str:
    h = int(s // 3600)
    m = int((s % 3600) // 60)
    sec = s % 60
    return f"{h:02d}:{m:02d}:{int(sec):02d},{int(sec % 1 * 1000):03d}"


def _build_srt(words: list[dict], offset: float, chunk_size: int = 7) -> str:
    chunks, current, t_start = [], [], None
    for w in words:
        if t_start is None:
            t_start = w["start"] - offset
        current.append(w)
        if len(current) >= chunk_size:
            chunks.append((t_start, current[-1]["end"] - offset, [x["text"] for x in current]))
            current, t_start = [], None
    if current:
        chunks.append((t_start, current[-1]["end"] - offset, [x["text"] for x in current]))

    lines = []
    for i, (s, e, ws) in enumerate(chunks, 1):
        lines += [str(i), f"{_srt_ts(s)} --> {_srt_ts(e)}", " ".join(ws), ""]
    return "\n".join(lines)


# ── Host images ───────────────────────────────────────────────────────────────

def _ensure_host_images() -> tuple[Path, Path]:
    paths = [Path("assets/host1.jpg"), Path("assets/host2.jpg")]
    if all(p.exists() for p in paths):
        return paths[0], paths[1]

    import base64
    from openai import OpenAI
    client = OpenAI()
    descs = [
        "Professional podcast host, confident and articulate, neutral studio background, close-up headshot, photorealistic, looking toward camera",
        "Curious podcast co-host, engaged and thoughtful expression, neutral studio background, close-up headshot, photorealistic, looking toward camera",
    ]
    for path, desc in zip(paths, descs):
        if not path.exists():
            typer.echo(f"  Generating {path.name} via gpt-image-1…")
            r = client.images.generate(model="gpt-image-1", prompt=desc, size="1024x1024", n=1)
            path.write_bytes(base64.b64decode(r.data[0].b64_json))
    return paths[0], paths[1]


# ── HeyGen API ────────────────────────────────────────────────────────────────

def _heygen_headers() -> dict:
    return {"X-Api-Key": os.environ["HEYGEN_API_KEY"]}


def _heygen_upload(file_path: Path) -> str:
    """Upload a file to HeyGen and return the asset ID."""
    suffix = file_path.suffix.lower()
    content_type = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".mp3": "audio/mpeg",
    }.get(suffix, "application/octet-stream")

    resp = httpx.post(
        _HEYGEN_UPLOAD,
        headers={**_heygen_headers(), "Content-Type": content_type},
        content=file_path.read_bytes(),
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["data"]["id"]


def _load_heygen_ids() -> dict:
    if _HEYGEN_IDS_CACHE.exists():
        return json.loads(_HEYGEN_IDS_CACHE.read_text())
    return {}


def _save_heygen_ids(ids: dict) -> None:
    _HEYGEN_IDS_CACHE.parent.mkdir(parents=True, exist_ok=True)
    _HEYGEN_IDS_CACHE.write_text(json.dumps(ids, indent=2))


def _ensure_host_asset_ids(host1_img: Path, host2_img: Path) -> tuple[str, str]:
    """Return cached HeyGen asset IDs for host images, uploading if needed."""
    ids = _load_heygen_ids()
    changed = False

    for key, path in [("host1", host1_img), ("host2", host2_img)]:
        if key not in ids:
            typer.echo(f"  Uploading {path.name} to HeyGen…")
            ids[key] = _heygen_upload(path)
            changed = True

    if changed:
        _save_heygen_ids(ids)

    return ids["host1"], ids["host2"]


def _heygen_talking_head(image_asset_id: str, audio_path: Path) -> Path:
    """Generate a HeyGen talking photo video. Returns path to downloaded MP4."""
    typer.echo(f"    Uploading audio ({audio_path.stat().st_size // 1024}KB)…")
    audio_asset_id = _heygen_upload(audio_path)

    resp = httpx.post(
        _HEYGEN_GENERATE,
        headers={**_heygen_headers(), "Content-Type": "application/json"},
        json={
            "dimension": {"width": 720, "height": 720},
            "video_inputs": [{
                "character": {
                    "type": "talking_photo",
                    "talking_photo_id": image_asset_id,
                    "talking_style": "expressive",
                },
                "voice": {
                    "type": "audio",
                    "audio_asset_id": audio_asset_id,
                },
            }],
        },
        timeout=30,
    )
    resp.raise_for_status()
    video_id = resp.json()["data"]["video_id"]

    deadline = time.time() + _POLL_TIMEOUT
    while time.time() < deadline:
        time.sleep(_POLL_INTERVAL)
        r = httpx.get(_HEYGEN_STATUS, headers=_heygen_headers(), params={"video_id": video_id}, timeout=30)
        r.raise_for_status()
        data = r.json()["data"]
        if data["status"] == "completed":
            video = httpx.get(data["video_url"], timeout=120)
            tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
            tmp.write(video.content)
            tmp.close()
            return Path(tmp.name)
        if data["status"] == "failed":
            raise RuntimeError(f"HeyGen failed: {data.get('error')}")

    raise TimeoutError("HeyGen video generation timed out")


# ── Video assembly ────────────────────────────────────────────────────────────

def _assemble(segments: list[Path], srt_path: Path, output_path: Path) -> None:
    """Concat segments, scale to 9:16 with blurred background, burn captions."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        for seg in segments:
            f.write(f"file '{seg.resolve()}'\n")
        concat_list = f.name

    joined = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False).name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", joined],
            check=True, capture_output=True,
        )

        vf = (
            "[0:v]split=2[fg_src][bg_src];"
            "[bg_src]scale=1080:1920:force_original_aspect_ratio=increase,"
            "crop=1080:1920,boxblur=30:5[bg];"
            "[fg_src]scale=1080:-2[fg];"
            "[bg][fg]overlay=(W-w)/2:((H-h)/2)-80[composed];"
            f"[composed]subtitles={srt_path.resolve()}:"
            "force_style='FontSize=24,Alignment=2,PrimaryColour=&HFFFFFF&,"
            "OutlineColour=&H000000&,Outline=2,Bold=1,MarginV=60'"
        )
        subprocess.run(
            ["ffmpeg", "-y", "-i", joined,
             "-filter_complex", vf,
             "-c:v", "libx264", "-crf", "22", "-preset", "fast",
             "-c:a", "aac", "-b:a", "128k",
             str(output_path)],
            check=True, capture_output=True,
        )
    finally:
        os.unlink(concat_list)
        os.unlink(joined)


# ── Main ─────────────────────────────────────────────────────────────────────

@app.command()
def main(
    audio: str = typer.Argument(..., help="Path to episode MP3"),
    script: str = typer.Option(..., "--script", help="Path to script.json (output/episodes/NNN/script.json)"),
    duration: int = typer.Option(75, "--duration", help="Target clip duration in seconds"),
    output: str = typer.Option("", "--output", help="Output MP4 path (default: alongside audio)"),
) -> None:
    config = _load_config()
    audio_path = Path(audio)
    script_path = Path(script)
    out_path = Path(output) if output else audio_path.with_suffix(".clip.mp4")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    typer.echo(f"\nLoading script: {script_path}")
    script_lines = _load_script(script_path)
    spoken = [l for l in script_lines if l.speaker != 0]
    typer.echo(f"{len(spoken)} spoken lines")

    # 1. Select highlight
    typer.echo("\nSelecting highlight…")
    start_idx, end_idx = _select_highlight(spoken, duration)
    highlight = spoken[start_idx: end_idx + 1]
    typer.echo(f"Lines {start_idx}–{end_idx} ({len(highlight)} lines)")

    with tempfile.TemporaryDirectory() as _tmp:
        tmp = Path(_tmp)

        # 2. Rough position estimate → padded clip
        rough_start, rough_end = _estimate_position(script_lines, start_idx, end_idx, config)
        typer.echo(f"\nEstimated position: {rough_start:.1f}s – {rough_end:.1f}s (padded)")
        rough_clip = tmp / "rough.mp3"
        _ffmpeg_cut(audio_path, rough_start, rough_end, rough_clip)

        # 3. Forced alignment on padded clip → precise timestamps
        typer.echo("Aligning text to audio…")
        clip_text = " ".join(l.text for l in highlight)
        words = _forced_alignment(rough_clip, clip_text)
        if not words:
            typer.echo("Error: forced alignment returned no words.", err=True)
            raise typer.Exit(1)

        precise_start = rough_start + words[0]["start"]
        precise_end = rough_start + words[-1]["end"]
        typer.echo(f"Clip: {precise_start:.2f}s – {precise_end:.2f}s ({precise_end - precise_start:.1f}s)")

        # 4. Extract final clip audio
        clip_audio = tmp / "clip.mp3"
        _ffmpeg_cut(audio_path, precise_start, precise_end, clip_audio)

        # 5. SRT captions
        srt_path = tmp / "captions.srt"
        srt_path.write_text(_build_srt(words, words[0]["start"]))

        # 6. Host images + HeyGen asset IDs
        typer.echo("\nChecking host images…")
        host1_img, host2_img = _ensure_host_images()
        typer.echo("Ensuring HeyGen asset IDs…")
        host1_id, host2_id = _ensure_host_asset_ids(host1_img, host2_img)

        # 7. Per-speaker-turn: split audio, generate talking head
        typer.echo("\nGenerating talking head segments…")
        video_segs: list[Path] = []
        word_cursor = 0
        for i, line in enumerate(highlight):
            n = len(line.text.split())
            seg_words = words[word_cursor: word_cursor + n]
            word_cursor += n
            if not seg_words:
                continue

            seg_start = seg_words[0]["start"] - words[0]["start"]
            seg_end = seg_words[-1]["end"] - words[0]["start"]
            seg_audio = tmp / f"seg_{i:03d}.mp3"
            _ffmpeg_cut(clip_audio, seg_start, seg_end, seg_audio)

            img_id = host1_id if line.speaker == 1 else host2_id
            typer.echo(f"  [{i + 1}/{len(highlight)}] host{line.speaker} ({seg_end - seg_start:.1f}s)…")
            video_segs.append(_heygen_talking_head(img_id, seg_audio))

        # 8. Assemble final video
        typer.echo("\nAssembling video…")
        _assemble(video_segs, srt_path, out_path)

    for seg in video_segs:
        try:
            os.unlink(seg)
        except FileNotFoundError:
            pass

    typer.echo(f"\nClip saved → {out_path}")


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).parent.parent))
    app()
