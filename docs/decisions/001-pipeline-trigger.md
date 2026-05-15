# ADR 001 — Pipeline Trigger Mechanism

**Status:** Accepted  
**Date:** 2026-05-15

---

## Context

The Notecast pipeline needs an invocation mechanism: something accepts a question, kicks off the research → script → TTS → feed sequence, and manages secrets (API keys for Tavily, ElevenLabs, Anthropic, AWS).

The primary requirements for the PoC are:
- Minimal infrastructure to stand up
- Secrets management without a secrets server
- Sufficient compute time for a 2–5 minute pipeline run
- Acceptable end-to-end latency for personal use

---

## Decision

Use **GitHub Actions** as the pipeline trigger for the proof of concept.

Questions are submitted via `workflow_dispatch` (manual trigger with a text input field in the GitHub UI) or `repository_dispatch` (API call for future CLI integration). The workflow checks out the repo, installs dependencies, runs the pipeline, and uploads the resulting MP3 to S3.

---

## Rationale

- Zero infrastructure to manage — no Lambda, no API Gateway, no EventBridge rules
- Native secrets management via repository secrets (no secrets server needed)
- Free tier (2,000 min/month for private repos) covers ~200–400 episodes/month — well above personal use
- 6-hour job timeout is not a constraint for a sub-10-minute pipeline
- `workflow_dispatch` provides a functional "submit question" UI without building a FastAPI endpoint

---

## Consequences

- **Runner startup lag (~30–60s):** Total latency from question submission to episode availability is 3–7 minutes rather than sub-minute. Acceptable for personal use; would matter for a responsive product.
- **No persistent state on the runner:** All state (MP3s, `podcast.xml`) lives in S3. Runners are ephemeral by design — this is not a problem.
- **No streaming or real-time feedback:** The pipeline is a black box until the job completes. A future UI could poll the Actions API for job status.
- **GitHub dependency:** The trigger is coupled to GitHub. Migrating away from GitHub would require rewiring invocation.

---

## Future Path

When any of these conditions are met, revisit in favor of **AWS Lambda + EventBridge**:

- Latency becomes unacceptable (runner startup is the bottleneck, not pipeline duration)
- Invocation volume exceeds GitHub Actions free tier
- A low-latency API endpoint is needed (e.g., Shortcut or mobile app integration)
- The pipeline needs to be triggered by external events (calendar, RSS diff, webhook)

The Lambda architecture would be:

```
[EventBridge rule / API Gateway endpoint]
        |
        v
[Lambda function — pipeline orchestrator]
  |-- Pulls question from event payload
  |-- Runs LangGraph research agent (may need Step Functions for long chains)
  |-- Calls Claude, ElevenLabs
  |-- Uploads MP3 to S3, regenerates podcast.xml
        |
        v
[S3 + RSS feed — same as PoC]
```

Secrets would move to AWS Secrets Manager or Parameter Store. The S3 output layer is identical, so the podcast feed subscription URL does not change when the trigger is swapped.
