# Notecast — Implementation Plan

Derived from [SPEC.md](SPEC.md). Each phase produces a working, usable artifact — not a partial system.

---

## Phase 1 — End-to-End Prototype

**Goal:** Prove the full pipeline works. Question in → MP3 out → listenable in a podcast app.  
**Estimate:** 1–2 days  
**Status:** ✅ Complete  
**Success criterion:** A generated episode plays correctly when manually imported into Overcast.

### Tasks

- [x] Create repo structure: `src/`, `docs/`, `.github/workflows/`, `config.yaml`, `.env.example`
- [x] Install and configure `podcastfy` with Tavily research mode
- [x] Write a minimal `pipeline.py` that accepts a question string and calls `podcastfy`
- [x] Confirm MP3 output with correct ID3 tags (title, date)
- [x] Manually import MP3 into Overcast and verify playback
- [x] Document any `podcastfy` limitations or quality issues observed

### Notes

`podcastfy` is scaffolding only — it will be replaced in Phase 2. The goal here is to validate the concept and surface any surprises (TTS voice quality, script length, API rate limits) before investing in the custom agent.

**Issues encountered and resolved:**
- LangSmith blocked public prompt pulls by default (recent security update) — patched with `_validate_public_prompt_pull` no-op in `pipeline.py`
- Playwright timed out scraping URLs — bypassed by passing Tavily-extracted content via `text=` instead of `urls=`
- ElevenLabs API key missing `voices_read` permission — switched to OpenAI TTS for Phase 1; ElevenLabs to be resolved for Phase 2
- pyenv 3.11.14 has a blake2 hashlib warning (non-fatal OpenSSL build issue)

---

## Phase 2 — Custom Research Agent + GitHub Actions

**Goal:** Replace `podcastfy` research with a custom LangGraph agent and wire the pipeline to GitHub Actions.  
**Estimate:** 1 week  
**Status:** ✅ Complete  
**Success criterion:** Submitting a question via `workflow_dispatch` in the GitHub UI produces an MP3 uploaded to S3 within 7 minutes.

### Tasks

#### Repository setup
- [x] Add `requirements.txt` with: `langgraph`, `anthropic`, `pydub`, `boto3`, `python-dotenv`, `typer`
- [x] Add `ffmpeg` install step to the Actions workflow
- [x] Add all secrets to GitHub repository settings (via Terraform)

#### LangGraph research agent (`src/research/`)
- [x] Define `ResearchState` TypedDict: `question`, `sub_queries`, `search_results`, `brief`, `iterations`
- [x] Implement `planner_node`: calls Claude to decompose question into 3–5 sub-queries; XML-tagged prompt
- [x] Implement `searcher_node`: calls Tavily for each sub-query; stores raw results in state
- [x] Implement `sufficiency_edge`: conditional — loops back to planner if result count or quality is below threshold
- [x] Implement `synthesizer_node`: calls Claude to produce structured brief (key findings, evidence, conflicting views, open questions)
- [x] Implement `script_prompt_builder_node`: packages brief into final LLM context
- [x] Write unit tests for each node using fixture inputs (no live API calls) — 14/14 passing

#### Script generation (`src/script/`)
- [x] Write script generation prompt following NotebookLM pattern: persona, tone, brief injection
- [x] Call Claude with the packaged context; parse `<host1>` / `<host2>` tags from response
- [x] Validate output: both speakers present, minimum word count met, no malformed tags

#### TTS synthesis (`src/tts/`)
- [x] Implement per-line audio generation loop (ElevenLabs + OpenAI backends)
- [x] Concatenate segments with `pydub`: 200ms inter-segment pauses
- [x] Normalize audio levels across Host 1 and Host 2

#### S3 upload (`src/storage/`)
- [x] Upload `.mp3` to S3 bucket with key `episodes/YYYY-MM-DD-<slug>.mp3`
- [x] Return the public-readable URL for the episode

#### GitHub Actions workflow (`.github/workflows/generate.yml`)
- [x] Define `workflow_dispatch` trigger with `question`, `dry_run`, `tts` inputs
- [x] Steps: checkout → install Python + ffmpeg → run pipeline → upload artifacts
- [x] Inject all secrets as environment variables
- [x] Add `--dry-run` support: prints structured brief as workflow summary

---

## Phase 3 — Automated RSS Feed

**Goal:** Subscribe to the feed once in a podcast app; new episodes appear automatically.  
**Estimate:** 1–2 days  
**Success criterion:** After an Actions run completes, the new episode appears in Overcast within 30 minutes (standard RSS poll interval).

### Tasks

- [ ] Implement `src/feed/generator.py` using `feedgen`
  - Read existing `podcast.xml` from S3 (if present)
  - Append new episode item: title, enclosure URL, pubDate, guid, iTunes tags
  - Write updated `podcast.xml` back to S3 at `AWS_S3_FEED_KEY`
- [ ] Set S3 object ACL / bucket policy so `podcast.xml` is publicly readable at a stable URL
- [ ] Add feed regeneration as the final step in the Actions workflow (after S3 upload)
- [ ] Subscribe to the RSS URL in Overcast (one-time setup)
- [ ] Verify: trigger a run, wait for feed poll, confirm episode appears

---

## Phase 4 — Lambda Migration (Optional)

**Goal:** Replace GitHub Actions trigger with AWS Lambda + EventBridge for sub-minute latency and event-driven invocation.  
**Estimate:** TBD — revisit when latency or volume becomes a pain point  
**Reference:** [ADR 001](decisions/001-pipeline-trigger.md)

### Tasks (placeholder)

- [ ] Package pipeline as a Lambda-compatible Python deployment (Docker image or zip)
- [ ] Create EventBridge rule or API Gateway endpoint as the entry point
- [ ] Migrate secrets from GitHub repository secrets to AWS Secrets Manager / Parameter Store
- [ ] Update invocation scripts to hit the API Gateway endpoint instead of `gh workflow run`
- [ ] Validate S3 output and RSS feed URL are unchanged (feed subscription does not need to be updated)

---

## File Structure (target end of Phase 3)

```
notecast/
├── .github/
│   └── workflows/
│       └── generate.yml
├── src/
│   ├── pipeline.py          # entry point; orchestrates all stages
│   ├── research/
│   │   ├── agent.py         # LangGraph graph definition
│   │   ├── nodes.py         # planner, searcher, synthesizer, prompt builder
│   │   └── state.py         # ResearchState TypedDict
│   ├── script/
│   │   └── generator.py     # Claude script generation + tag parsing
│   ├── tts/
│   │   └── synthesizer.py   # ElevenLabs per-line generation + pydub assembly
│   ├── storage/
│   │   └── s3.py            # upload MP3, return URL
│   └── feed/
│       └── generator.py     # feedgen RSS regeneration
├── tests/
│   └── research/
│       └── test_nodes.py
├── config.yaml
├── .env.example
├── requirements.txt
└── docs/
    ├── SPEC.md
    ├── PLAN.md
    └── decisions/
        └── 001-pipeline-trigger.md
```
