"""
Notecast pipeline — Phase 2.

Usage:
  python src/pipeline.py "What is the current state of LLM reasoning?"
  python src/pipeline.py "..." --dry-run     # research + brief only, no audio
  python src/pipeline.py "..." --tts openai  # override TTS provider
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import typer
import yaml
from dotenv import load_dotenv

load_dotenv()

app = typer.Typer(add_completion=False)


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def _episode_slug(question: str) -> str:
    date = datetime.now().strftime("%Y-%m-%d")
    slug = question[:50].lower()
    slug = "".join(c if c.isalnum() or c == " " else "" for c in slug)
    slug = "-".join(slug.split())
    return f"{date}-{slug}"


@app.command()
def main(
    question: str = typer.Argument(..., help="Research question for the episode"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Research only; skip audio generation"),
    tts: str = typer.Option("", "--tts", help="Override TTS provider (elevenlabs|openai)"),
    output_dir: str = typer.Option("", "--output-dir", help="Override output directory"),
) -> None:
    config = load_config()
    if tts:
        config.setdefault("tts", {})["provider"] = tts

    out_dir = Path(output_dir or config.get("output_dir", "output"))
    out_dir.mkdir(parents=True, exist_ok=True)

    # ── Stage 1-2: Agentic research ───────────────────────────────────────────
    from src.research.agent import run_research

    typer.echo(f"\nResearching: {question}")
    state = run_research(question)

    sources = [r["url"] for item in state["search_results"] for r in item["results"]]
    typer.echo(f"Sources ({len(sources)}):")
    for url in sources:
        typer.echo(f"  {url}")

    brief_path = out_dir / "structured_brief.json"
    brief_path.write_text(json.dumps({
        "question": question,
        "sub_queries": state["sub_queries"],
        "brief": state["brief"],
        "sources": sources,
    }, indent=2))
    typer.echo(f"Brief saved → {brief_path}")

    if dry_run:
        typer.echo("\n[dry-run] Halting before audio generation.")
        typer.echo(f"\n{state['brief']}")
        return

    # ── Stage 3: Script generation ────────────────────────────────────────────
    from src.script.generator import generate_script

    typer.echo("\nGenerating script…")
    script_lines = generate_script(context=state["script_context"], config=config)
    word_count = sum(len(l.text.split()) for l in script_lines)
    typer.echo(f"Script: {len(script_lines)} lines, {word_count} words")

    # ── Stage 4: TTS synthesis ────────────────────────────────────────────────
    from src.tts.synthesizer import synthesize

    slug = _episode_slug(question)
    audio_path = out_dir / "audio" / f"{slug}.mp3"
    provider = config.get("tts", {}).get("provider", "openai")
    typer.echo(f"\nSynthesizing audio ({provider}, {len(script_lines)} segments)…")
    synthesize(script_lines, config, audio_path)
    typer.echo(f"Audio saved → {audio_path}")

    # ── Stage 5: S3 upload ────────────────────────────────────────────────────
    if os.environ.get("AWS_S3_BUCKET"):
        from src.storage.s3 import upload_episode

        typer.echo("\nUploading to S3…")
        episode_url = upload_episode(audio_path)
        typer.echo(f"Episode URL: {episode_url}")

        # ── Stage 6: RSS feed update ──────────────────────────────────────────
        from pydub import AudioSegment
        from src.feed.generator import Episode, update_feed

        file_size = audio_path.stat().st_size
        duration = int(AudioSegment.from_mp3(str(audio_path)).duration_seconds)
        pub_date = datetime.now(tz=timezone.utc).isoformat()

        episode = Episode(
            guid=slug,
            title=f"Episode: {question[:80]}",
            description=state["brief"][:500],
            url=episode_url,
            pub_date=pub_date,
            file_size=file_size,
            duration=duration,
        )

        typer.echo("\nUpdating RSS feed…")
        feed_url = update_feed(episode, config)
        typer.echo(f"Feed URL: {feed_url}")
    else:
        typer.echo("\n[skip] AWS_S3_BUCKET not set — skipping S3 upload and feed update.")

    typer.echo("\nDone.")


if __name__ == "__main__":
    # Ensure src/ is on the path when run directly
    sys.path.insert(0, str(Path(__file__).parent.parent))
    app()
