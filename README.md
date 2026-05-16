# Notecast

A personal tool that turns research questions into private podcast episodes. Ask a question, get a two-host conversational audio episode delivered to your podcast app within minutes.

```
"What is the current state of LLM reasoning?"
         ↓
  Tavily web research
         ↓
  Claude script generation
         ↓
  Claude fact-check + rewrite pass
         ↓
  ElevenLabs two-voice TTS
         ↓
  Private RSS feed on S3
```

Episodes are delivered to a private RSS feed you subscribe to once in any podcast app (Overcast, Pocket Casts, Apple Podcasts). New episodes appear automatically.

---

## Prerequisites

- Python 3.11+
- `ffmpeg` (`brew install ffmpeg` on macOS)
- API keys for: [Tavily](https://tavily.com), [Anthropic](https://console.anthropic.com), [ElevenLabs](https://elevenlabs.io) or OpenAI
- An AWS account with S3 access
- Terraform 1.5+ (for infrastructure setup)

---

## Setup

### 1. Clone and create a virtual environment

```bash
git clone https://github.com/your-username/Notecast.git
cd Notecast
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure API keys

```bash
cp .env.example .env
```

Edit `.env` and fill in your API keys:

```
TAVILY_API_KEY=tvly-...
ANTHROPIC_API_KEY=sk-ant-...
ELEVENLABS_API_KEY=sk_...
OPENAI_API_KEY=sk-proj-...    # optional TTS fallback
```

### 3. Set up AWS infrastructure

The `infrastructure/` directory contains Terraform that creates the S3 bucket and sets all required GitHub Actions secrets automatically.

```bash
cp infrastructure/terraform.tfvars.example infrastructure/terraform.tfvars
```

Edit `terraform.tfvars` with your values, then:

```bash
cd infrastructure
terraform init
terraform apply
```

After apply, the `feed_url` output gives you the RSS URL to subscribe to in your podcast app.

---

## Running locally

Activate the virtual environment first, or prefix commands with `.venv/bin/python`:

```bash
# Option A — activate once per shell session
source .venv/bin/activate

# Option B — explicit path, no activation needed
alias p=".venv/bin/python"
```

Then run the pipeline:

```bash
# Research only — no audio generated, writes output/structured_brief.json
python -m src.pipeline "What is the current state of LLM reasoning?" --dry-run

# Full run — generates an MP3 in output/audio/
python -m src.pipeline "What is the current state of LLM reasoning?"

# Use a specific TTS provider
python -m src.pipeline "..." --tts openai

# Use a local markdown file as research context (question auto-derived from the document)
python -m src.pipeline --file path/to/notes.md

# File + explicit question to focus the research angle
python -m src.pipeline "What does recent research say about X?" --file path/to/notes.md

# Upload an already-generated MP3 to S3 and update the feed
python -m src.pipeline "My question" --from-audio output/audio/episode.mp3
```

---

## Running via GitHub Actions

After Terraform has set the repository secrets, trigger a run from the GitHub UI:

**Actions → Generate Episode → Run workflow → enter your question**

Or via the GitHub CLI:

```bash
gh workflow run generate.yml -f question="What is the current state of LLM reasoning?"
```

The episode is uploaded to S3 and appears in your podcast feed automatically.

---

## Configuration

[`config.yaml`](config.yaml) controls tunable defaults with no secrets:

| Key | Default | Description |
|-----|---------|-------------|
| `tts.provider` | `elevenlabs` | TTS backend (`elevenlabs`, `openai`) |
| `tts.elevenlabs_voices.host1/host2` | Adam / Bella | ElevenLabs voice IDs — find at elevenlabs.io/voice-library |
| `tts.elevenlabs_speed.host1/host2` | 1.2 / 1.0 | Per-host speaking rate (0.7–1.2) |
| `tts.openai_voices.host1/host2` | onyx / nova | OpenAI voice names |
| `tts.openai_speed.host1/host2` | 1.0 / 1.0 | Per-host speaking rate (0.25–4.0) |
| `script.word_count` | `3000` | Target script length (~10–15 min episode) |
| `script.fact_check` | `true` | Rewrite unsupported script claims against the research brief |
| `research.max_results` | `5` | Number of Tavily sources per question |
| `research.days` | `90` | Only return results published within this many days |
| `intro_music.path` | `assets/intro.mp3` | Path to intro music file |
| `intro_music.overlap_ms` | `2000` | Music fades in this many ms before intro speech ends |
| `intro_music.sting_ms` | `10000` | Music plays solo at full volume after intro (ms) |
| `intro_music.fade_in_ms` | `1500` | Fade-in duration while overlapping with speech (ms) |
| `intro_music.fade_out_ms` | `2000` | Fade-out duration into the episode (ms) |
| `intro_music.duck_db` | `14` | dB reduction of music while speech is still playing |
| `podcast_name` | `Notecast` | Name used in RSS feed and episode metadata |

---

## Intro music

Place a music file at `assets/intro.mp3`. The hosts deliver a short setup, music fades in under the last few seconds of their speech, plays briefly at full volume, then fades out into the episode.

The timing is fully configurable in `config.yaml` under `intro_music`. Key settings:

- **`overlap_ms`** — how many ms before the intro ends the music starts fading in (default 2000)
- **`sting_ms`** — how long the music plays solo after the hosts finish (default 10000)
- **`duck_db`** — how much to reduce music volume while speech is still playing (default 14dB)

If `assets/intro.mp3` is not present the episode assembles normally without music.

---

## Document-based research

Pass a local markdown file as the research source. Notecast extracts key claims from the document and uses them to drive independent web research, supplementing the document with current sources.

```bash
# Question auto-derived from the document
python -m src.pipeline --file path/to/notes.md

# Explicit question to focus the research angle
python -m src.pipeline "What does recent research say about X?" --file path/to/notes.md

# Dry run to preview the research brief before generating audio
python -m src.pipeline --file path/to/notes.md --dry-run
```

The document's key points are extracted by Claude and injected into the research agent as context — the web research supplements and verifies the document's claims rather than replacing them. The hosts will not cite the file directly; the content informs the script naturally through the research brief.

---

## Project structure

```
src/pipeline.py               # main entry point
src/document.py               # markdown file pre-processor
src/research/                 # LangGraph research agent
src/script/                   # Claude script generation + fact-check
src/tts/                      # ElevenLabs / OpenAI TTS + audio assembly
src/storage/                  # S3 upload
src/feed/                     # RSS feed generation
assets/intro.mp3              # intro music (add your own)
config.yaml                   # tunable defaults
.env.example                  # API key template
infrastructure/               # Terraform — S3 bucket + GitHub secrets
.github/workflows/generate.yml  # GitHub Actions trigger
docs/
  SPEC.md                     # technical specification
  PLAN.md                     # phased implementation plan
  decisions/                  # architecture decision records
```

---

## Cost

Roughly **$0.19–0.53 per episode** (Claude + Tavily), plus TTS:

| Service | Cost |
|---------|------|
| Tavily search | ~$0.01–0.05 |
| Claude research (planner + synthesizer + description) | ~$0.03–0.08 |
| Claude script generation | ~$0.07–0.15 |
| Claude fact-check + rewrite pass | ~$0.08–0.15 |
| ElevenLabs TTS | Starter plan ($5/mo) covers ~1–2 episodes/month at 3,000 words (~15–18K chars); upgrade to Creator ($22/mo) for ~5–6 episodes/month |
| OpenAI TTS (alternative) | ~$0.45–0.55/episode — no monthly cap, better for higher volume |
| S3 | negligible |

---

## Architecture

See [`docs/SPEC.md`](docs/SPEC.md) for the full technical specification and [`docs/decisions/`](docs/decisions/) for architecture decision records.
