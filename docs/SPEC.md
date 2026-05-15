# Notecast — Technical Specification

## Purpose

Notecast is a personal tool that accepts research questions, conducts multi-step web research, generates a two-host conversational podcast script, synthesizes it into audio, and delivers episodes to a private RSS feed subscribable in any podcast app.

---

## System Overview

The pipeline has four sequential stages, orchestrated by GitHub Actions:

```
[Question Input: workflow_dispatch / repository_dispatch]
      |
      v
[GitHub Actions runner]
      |
      v
[Agentic Research]  →  structured_brief.json
      |
      v
[Script Generation]  →  tagged two-speaker script
      |
      v
[TTS Synthesis]  →  .mp3 with ID3 tags
      |
      v
[Feed Delivery]  →  RSS feed on S3
```

---

## Stage 1 — Question Intake

**Interface:** GitHub Actions `workflow_dispatch` (PoC). Questions are submitted via the GitHub UI or the GitHub API (`repository_dispatch`) for future CLI integration. See [ADR 001](decisions/001-pipeline-trigger.md) for the decision record and the future Lambda + EventBridge path.

**Input forms:**
- `workflow_dispatch` with a `question` input field — manual trigger via GitHub UI or `gh workflow run`
- `repository_dispatch` event with a `question` payload — callable from a local CLI wrapper or any HTTP client
- Batch: multiple questions in the payload produce a single thematic episode

**Design decisions:**
- Multiple related questions are batched into one episode for a more natural conversational arc.
- The pipeline script must support a `--dry-run` flag that halts after research and prints the structured brief without generating audio.
- Expected end-to-end latency: 3–7 minutes (30–60s runner startup + ~2–5 min pipeline).

---

## Stage 2 — Agentic Research

**Framework:** LangGraph (stateful, cyclical graph with conditional edges)

**Graph nodes:**

| Node | Responsibility |
|------|---------------|
| Planner | Decomposes the question into 3–5 targeted sub-queries |
| Searcher | Calls Tavily API; loops back to Planner if results are insufficient |
| Synthesizer | Produces a `structured_brief.json` with: key findings, supporting evidence, conflicting viewpoints, open questions |
| Script Prompt Builder | Packages the brief into the final LLM context |

**Shared state:** A `ResearchState` TypedDict passed through all nodes.

**Search API:** Tavily (primary). Tavily is chosen for its LangGraph/LangChain native integration, LLM-ready JSON output, and built-in prompt injection firewall. Perplexity Sonar is the backup — it collapses search + synthesis into one call at higher cost.

**Prompt conventions (Anthropic context engineering):**
- All agent prompts use XML-tagged sections: `<instructions>`, `<background_information>`, `<output_format>`
- All inter-node outputs are JSON or Markdown — never free-form text
- The Synthesizer output is a structured Markdown brief, not prose

**Output:** `structured_brief.json` written to a working directory for the episode.

---

## Stage 3 — Script Generation

**Model:** Claude (claude-sonnet-4-6 default; configurable). GPT-4o is a drop-in alternative.

**Format:** Two-speaker conversational script tagged as `<host1>...</host1>` / `<host2>...</host2>` for direct TTS parsing.

**Speaker roles:**
- **Host 1:** synthesizes research findings in 2–3 minute segments
- **Host 2:** asks clarifying questions, introduces counterpoints, drives pacing

**Script structure:**
1. Episode hook referencing the user's question
2. Alternating Host 1 / Host 2 exchanges covering the structured brief
3. Natural verbal fillers and hesitations for realism
4. Closing summary and open questions for future episodes

**Target length:** 10–25 minutes of audio (~2,500–6,000 words of script).

**Prompt includes:** explicit tone, safety, and compliance instructions alongside the content brief (following the NotebookLM pattern).

**Fact-check pass:** After script generation, a second Claude call compares every factual claim in the script against the research brief. Any claim not supported by the brief is automatically rewritten to reflect what the sources actually say, preserving speaker voice and tone. This runs by default and is controlled by `script.fact_check` in `config.yaml`. It adds one API call (~$0.08–0.15) and prevents hallucinations from propagating into the final audio.

**Reference libraries:** `podcastfy` is available as a fallback for prototyping but will not be the long-term dependency — the custom LangGraph agent produces higher-quality research context.

---

## Stage 4 — TTS Synthesis

**Provider:** ElevenLabs (primary). Chosen for native multi-voice dialogue support, voice cloning from the Starter tier, and ~75ms latency.

**Voice assignment:**
- Host 1 and Host 2 are assigned distinct ElevenLabs voice IDs in config.
- Voice IDs are stored in environment variables / config file, not hardcoded.

**Audio assembly pipeline:**
1. Generate per-line `.wav` segments, one API call per tagged line.
2. Concatenate segments with 150–300ms inter-segment pauses using `pydub`.
3. Normalize audio levels across both speakers.
4. Export to `.mp3` with ID3 tags (title, episode number, description, date).

**Fallback:** OpenAI TTS-1-HD — 6 preset voices, no cloning, but outstanding quality and steerability via tone prompts. Suitable if ElevenLabs is unavailable or costs exceed budget.

**Dependencies:** `pydub`, `ffmpeg` (system dependency).

---

## Stage 5 — Feed Delivery

**Hosting:** AWS S3 (aligns with existing infrastructure).

**Mechanism:**
- Generated `.mp3` files are uploaded to a private S3 bucket.
- After each upload, `feedgen` (Python) regenerates `podcast.xml` and overwrites the existing file in S3.
- The RSS feed URL is a stable, obscure-path URL (no authentication required for podcast app compatibility).

**RSS envelope** includes: `<title>`, `<enclosure>` (URL + type + length), `<pubDate>`, `<guid>`, and iTunes namespace tags for app compatibility.

**Podcast clients:** Overcast, Pocket Casts, Apple Podcasts (all support manual RSS subscription). Spotify is not a target — it does not support private RSS feeds.

**Alternative:** Audiobookshelf (Docker) if S3 proves too complex for feed management. FolderCast/Podcats are dev/test options only.

---

## Technology Decisions

| Component | Selected | Rationale | Alternative |
|-----------|----------|-----------|-------------|
| Agent orchestration | LangGraph | Stateful cyclical graphs; native Tavily integration | CrewAI, AutoGen |
| Web search | Tavily | LLM-ready JSON, injection firewall, LangGraph plugin | Perplexity Sonar |
| Script LLM | Claude (claude-sonnet-4-6) | Quality + steerability; Anthropic SDK prompt caching | GPT-4o |
| TTS | ElevenLabs | Multi-voice dialogue, voice cloning | OpenAI TTS-1-HD |
| Audio assembly | pydub + ffmpeg | Mature, well-documented | audioop |
| RSS generation | feedgen | Programmatic API, iTunes namespace support | s3cast |
| Feed hosting | AWS S3 | Existing infrastructure | Audiobookshelf (Docker) |
| CLI framework | Typer | Modern, type-safe argparse replacement | argparse |
| Pipeline trigger | GitHub Actions | Zero infrastructure; native secrets management | AWS Lambda + EventBridge (see ADR 001) |

---

## Configuration

Secrets are stored as **GitHub repository secrets** and injected into the Actions runner as environment variables. For local development, the same variable names live in a `.env` file (not committed).

```
TAVILY_API_KEY
ELEVENLABS_API_KEY
ELEVENLABS_HOST1_VOICE_ID
ELEVENLABS_HOST2_VOICE_ID
ANTHROPIC_API_KEY
AWS_S3_BUCKET
AWS_S3_FEED_KEY          # path within bucket for podcast.xml
PODCAST_FEED_BASE_URL    # public base URL for MP3 links in the feed
```

A `config.yaml` (committed, no secrets) holds tunable defaults: target episode length, number of research sub-queries, inter-segment pause duration, TTS provider selection.

---

## Cost Model (per episode)

| Service | Estimated Cost |
|---------|----------------|
| Tavily search | ~$0.01–0.05 (1–2 credits per query × 5 queries) |
| Claude research (planner + synthesizer + description) | ~$0.03–0.08 |
| Claude script generation | ~$0.07–0.15 (varies with research depth and script length) |
| Claude fact-check + rewrite pass | ~$0.08–0.15 (full script + brief in, corrected script out) |
| ElevenLabs TTS | ~$0.00–0.10 (well within 30K char/mo Starter limit for personal use) |
| S3 storage + transfer | Negligible |
| **Total per episode** | **~$0.19–0.53** |

---

## Phased Build Plan

### Phase 1 — Prototype (1–2 days)
Use `podcastfy` with Tavily research mode enabled. Validate the end-to-end pipeline: question in → MP3 out. Import the MP3 manually into Overcast.

### Phase 2 — Custom Research Agent (1 week)
Replace `podcastfy` research with a custom LangGraph agent (Planner → Searcher → Synthesizer). Pass the structured brief into a custom Claude script prompt. Wire up a GitHub Actions workflow triggered via `workflow_dispatch`. Output MP3 to S3.

### Phase 3 — Automated Feed (1–2 days)
Add `feedgen` RSS regeneration after each S3 upload. Subscribe to the feed in the podcast app once — new episodes appear automatically after each Actions run.

### Phase 4 — Full Automation (optional)
Migrate trigger to AWS Lambda + EventBridge per [ADR 001](decisions/001-pipeline-trigger.md). Enables sub-minute invocation latency and event-driven triggers (calendar, webhook, RSS diff).

---

## Out of Scope

- Public podcast distribution (Spotify, Apple Podcasts directory listing)
- Multi-user support
- Real-time streaming audio
- Local/offline-only operation (Mozilla AI Blueprint pattern) — quality trade-off is not acceptable for daily use
- Video output
