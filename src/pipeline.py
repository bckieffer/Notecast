"""
Phase 1 prototype: Tavily research → podcastfy → MP3.

Usage:
  python src/pipeline.py "What is the current state of LLM reasoning?"
  python src/pipeline.py "..." --dry-run   # research only, no audio
  python src/pipeline.py "..." --tts openai
"""

import os
import json
from datetime import datetime
from pathlib import Path

import typer
import yaml
from dotenv import load_dotenv
from tavily import TavilyClient

# podcastfy pulls its prompt template from LangSmith Hub, which requires this
# flag since a recent LangSmith security update blocked public prompt pulls by
# default. Patched here because podcastfy doesn't expose the parameter.
# Irrelevant once Phase 2 replaces podcastfy with the custom LangGraph agent.
import langsmith.client as _ls
_ls._validate_public_prompt_pull = lambda *a, **kw: None

from podcastfy.client import generate_podcast

load_dotenv()

app = typer.Typer(add_completion=False)


def load_config() -> dict:
    config_path = Path(__file__).parent.parent / "config.yaml"
    with open(config_path) as f:
        return yaml.safe_load(f)


def research(question: str, config: dict) -> tuple[list[str], str]:
    """Search Tavily and return (source URLs, combined extracted content)."""
    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    res_cfg = config.get("research", {})
    response = client.search(
        query=question,
        max_results=res_cfg.get("max_results", 5),
        search_depth=res_cfg.get("search_depth", "advanced"),
    )
    results = response.get("results", [])
    urls = [r["url"] for r in results]
    # Tavily returns extracted content at advanced depth — use it directly
    # so podcastfy doesn't need to re-scrape with Playwright.
    content = "\n\n---\n\n".join(
        f"Source: {r['url']}\n\n{r.get('content', '')}" for r in results
    )
    return urls, content


@app.command()
def main(
    question: str = typer.Argument(..., help="Research question for the episode"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Research only; skip audio generation"),
    tts: str = typer.Option("", "--tts", help="Override TTS provider (elevenlabs|openai|edge)"),
    output_dir: str = typer.Option("", "--output-dir", help="Override output directory"),
) -> None:
    config = load_config()

    tts_model = tts or config.get("tts", {}).get("provider", "openai")
    out_dir = Path(output_dir or config.get("output_dir", "output"))
    out_dir.mkdir(parents=True, exist_ok=True)

    # Stage 1: Research
    typer.echo(f"\nResearching: {question}")
    urls, content = research(question, config)
    typer.echo(f"Found {len(urls)} sources:")
    for url in urls:
        typer.echo(f"  {url}")

    if dry_run:
        brief = {"question": question, "sources": urls}
        brief_path = out_dir / "structured_brief.json"
        brief_path.write_text(json.dumps(brief, indent=2))
        typer.echo(f"\n[dry-run] Brief written to {brief_path}")
        return

    # Stages 2–4: Script + TTS via podcastfy
    typer.echo(f"\nGenerating podcast (tts={tts_model}) …")

    script_cfg = config.get("script", {})
    conversation_config = {
        "word_count": script_cfg.get("word_count", 3000),
        "conversation_style": script_cfg.get("conversation_style", ["informative", "engaging"]),
        "roles_person1": script_cfg.get("roles_person1", "lead researcher"),
        "roles_person2": script_cfg.get("roles_person2", "curious questioner"),
        "dialogue_structure": script_cfg.get("dialogue_structure", ["Introduction", "Main Discussion", "Conclusion"]),
        "engagement_techniques": script_cfg.get("engagement_techniques", ["analogies", "rhetorical questions"]),
        "podcast_name": config.get("podcast_name", "Notecast"),
        "podcast_tagline": config.get("podcast_tagline", ""),
        "output_language": "English",
        "text_to_speech": {
            "output_directories": {
                "transcripts": str(out_dir / "transcripts"),
                "audio": str(out_dir / "audio"),
            }
        },
    }

    llm_cfg = config.get("llm", {})
    audio_path = generate_podcast(
        text=content,
        tts_model=tts_model,
        conversation_config=conversation_config,
        llm_model_name=llm_cfg.get("model", "anthropic/claude-sonnet-4-6"),
        api_key_label=llm_cfg.get("api_key_label", "ANTHROPIC_API_KEY"),
    )

    typer.echo(f"\nEpisode ready: {audio_path}")


if __name__ == "__main__":
    app()
