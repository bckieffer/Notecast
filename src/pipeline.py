"""
Notecast pipeline — Phase 2.

Usage:
  python src/pipeline.py "What is the current state of LLM reasoning?"
  python src/pipeline.py "..." --dry-run            # research + brief only, no audio
  python src/pipeline.py "..." --tts openai         # override TTS provider
  python src/pipeline.py "..." --from-audio PATH    # skip to S3 upload + feed update
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


def _save_script(script_lines: list, path: Path) -> None:
    from src.script.generator import ScriptLine
    data = [{"speaker": l.speaker, "text": l.text} for l in script_lines]
    path.write_text(json.dumps(data, indent=2))


def _load_script(path: Path) -> list:
    from src.script.generator import ScriptLine
    data = json.loads(path.read_text())
    return [ScriptLine(speaker=d["speaker"], text=d["text"]) for d in data]


@app.command()
def main(
    question: str = typer.Argument(default="", help="Research question for the episode"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Research only; skip audio generation"),
    tts: str = typer.Option("", "--tts", help="Override TTS provider (elevenlabs|openai)"),
    output_dir: str = typer.Option("", "--output-dir", help="Override output directory"),
    from_audio: str = typer.Option("", "--from-audio", help="Skip to S3 upload using an existing MP3"),
    file: str = typer.Option("", "--file", help="Markdown file to use as research context"),
) -> None:
    config = load_config()
    if tts:
        config.setdefault("tts", {})["provider"] = tts

    out_dir = Path(output_dir or config.get("output_dir", "output"))
    out_dir.mkdir(parents=True, exist_ok=True)

    if from_audio:
        if not question:
            typer.echo("Error: --from-audio requires a question.", err=True)
            raise typer.Exit(1)
        _upload_and_update_feed(Path(from_audio), question, brief="", config=config)
        return

    document_context = ""
    if file:
        from src.document import extract_document_context, load_document
        typer.echo(f"\nReading document: {file}")
        content = load_document(file)
        derived_question, document_context = extract_document_context(content, config)
        if not question:
            question = derived_question
            typer.echo(f"Derived question: {question}")

    if not question:
        typer.echo("Error: provide a question or --file.", err=True)
        raise typer.Exit(1)

    slug = _episode_slug(question)
    cache_dir = out_dir / "cache" / slug
    cache_dir.mkdir(parents=True, exist_ok=True)
    script_cache = cache_dir / "script.json"

    brief = ""

    if script_cache.exists():
        # ── Resume from cached script ─────────────────────────────────────────
        typer.echo(f"\n[cache] Loading script from {script_cache}")
        script_lines = _load_script(script_cache)
        word_count = sum(len(l.text.split()) for l in script_lines)
        typer.echo(f"Script: {len(script_lines)} lines, {word_count} words")
    else:
        # ── Stage 1-2: Agentic research ───────────────────────────────────────
        from src.research.agent import run_research

        typer.echo(f"\nResearching: {question}")
        state = run_research(question, config=config, document_context=document_context)

        sources = [r["url"] for item in state["search_results"] for r in item["results"]]
        typer.echo(f"Sources ({len(sources)}):")
        for url in sources:
            typer.echo(f"  {url}")

        # ── Stage 3: Episode outline ──────────────────────────────────────────
        from src.script.generator import generate_outline, generate_script

        typer.echo("\nGenerating episode outline…")
        outline = generate_outline(question=question, brief=state["brief"], config=config)
        typer.echo(f"Outline: {len(outline.split())} words")
        (cache_dir / "outline.md").write_text(outline)

        brief_path = cache_dir / "brief.json"
        brief_path.write_text(json.dumps({
            "question": question,
            "sub_queries": state["sub_queries"],
            "brief": state["brief"],
            "outline": outline,
            "sources": sources,
        }, indent=2))
        typer.echo(f"Brief saved → {brief_path}")

        if dry_run:
            typer.echo("\n[dry-run] Halting before audio generation.")
            typer.echo(f"\n{state['brief']}")
            typer.echo(f"\n--- Outline ---\n{outline}")
            return

        # ── Stage 4: Script generation ────────────────────────────────────────
        typer.echo("\nGenerating script…")
        script_lines = generate_script(context=state["script_context"], config=config, brief=state["brief"], outline=outline)
        word_count = sum(len(l.text.split()) for l in script_lines)
        typer.echo(f"Script: {len(script_lines)} lines, {word_count} words")
        _save_script(script_lines, script_cache)

        brief = state["brief"]

    # ── Stage 5: TTS synthesis ────────────────────────────────────────────────
    from src.tts.synthesizer import synthesize

    audio_path = out_dir / "audio" / f"{slug}.mp3"
    provider = config.get("tts", {}).get("provider", "openai")
    typer.echo(f"\nSynthesizing audio ({provider}, {len(script_lines)} segments)…")
    synthesize(script_lines, config, audio_path, cache_dir=cache_dir)
    typer.echo(f"Audio saved → {audio_path}")

    _upload_and_update_feed(audio_path, question, brief=brief, config=config, cache_dir=cache_dir)


def _upload_and_update_feed(audio_path: Path, question: str, brief: str, config: dict, cache_dir: Path | None = None) -> None:
    if not os.environ.get("AWS_S3_BUCKET"):
        typer.echo("\n[skip] AWS_S3_BUCKET not set — skipping S3 upload and feed update.")
        typer.echo("\nDone.")
        return

    from pydub import AudioSegment
    from src.feed.generator import Episode, update_feed
    from src.script.generator import generate_episode_description, generate_episode_title
    from src.storage.s3 import upload_episode

    typer.echo("\nUploading to S3…")
    episode_url = upload_episode(audio_path)
    typer.echo(f"Episode URL: {episode_url}")

    typer.echo("Generating episode title…")
    title = generate_episode_title(question, config)
    typer.echo(f"Title: {title}")

    typer.echo("Generating episode description…")
    description = generate_episode_description(question, brief, config) if brief else question
    typer.echo(f"Description: {description}")

    slug = audio_path.stem
    file_size = audio_path.stat().st_size
    duration = int(AudioSegment.from_mp3(str(audio_path)).duration_seconds)
    pub_date = datetime.now(tz=timezone.utc).isoformat()

    episode = Episode(
        guid=slug,
        title=title,
        description=description,
        url=episode_url,
        pub_date=pub_date,
        file_size=file_size,
        duration=duration,
    )

    typer.echo("\nUpdating RSS feed…")
    feed_url, episode_number = update_feed(episode, config)
    typer.echo(f"Feed URL: {feed_url}")

    if cache_dir and cache_dir.exists():
        import shutil
        out_dir = cache_dir.parent.parent
        episode_dir = out_dir / "episodes" / f"{episode_number:03d}"
        episode_dir.mkdir(parents=True, exist_ok=True)
        for fname in ("script.json", "brief.json", "outline.md"):
            src = cache_dir / fname
            if src.exists():
                shutil.copy2(src, episode_dir / fname)
        shutil.rmtree(cache_dir)
        typer.echo(f"[archive] Episode {episode_number:03d} collateral saved → {episode_dir}")

    typer.echo("\nDone.")


if __name__ == "__main__":
    # Ensure src/ is on the path when run directly
    sys.path.insert(0, str(Path(__file__).parent.parent))
    app()
