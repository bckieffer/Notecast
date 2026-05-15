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
python src/pipeline.py "What is the current state of LLM reasoning?" --dry-run

# Full run — generates an MP3 in output/audio/
python src/pipeline.py "What is the current state of LLM reasoning?"

# Use a specific TTS provider
python src/pipeline.py "..." --tts openai
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
| `tts.elevenlabs_voices.host1/host2` | Adam / Bella | ElevenLabs voice IDs |
| `tts.openai_voices.host1/host2` | onyx / nova | OpenAI voice names |
| `script.word_count` | `3000` | Target script length (~10–15 min episode) |
| `script.fact_check` | `true` | Rewrite unsupported script claims against the research brief |
| `research.max_results` | `5` | Number of Tavily sources per question |
| `research.days` | `90` | Only return results published within this many days |
| `podcast_name` | `Notecast` | Name used in RSS feed and episode metadata |

---

## Project structure

```
src/pipeline.py               # main entry point
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
