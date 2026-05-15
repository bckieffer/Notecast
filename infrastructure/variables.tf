# ── AWS ──────────────────────────────────────────────────────────────────────

variable "aws_region" {
  description = "AWS region for all resources"
  type        = string
  default     = "us-east-1"
}

variable "bucket_name" {
  description = "Globally unique S3 bucket name for episode storage and RSS feed"
  type        = string
}

variable "feed_key" {
  description = "S3 object key for the RSS feed file"
  type        = string
  default     = "podcast.xml"
}

# ── GitHub ────────────────────────────────────────────────────────────────────

variable "github_token" {
  description = "GitHub personal access token with repo and secrets:write scopes"
  type        = string
  sensitive   = true
}

variable "github_owner" {
  description = "GitHub username or organization that owns the repository"
  type        = string
}

variable "github_repo" {
  description = "GitHub repository name (without owner prefix)"
  type        = string
  default     = "Notecast"
}

# ── Third-party API keys ──────────────────────────────────────────────────────
# These are written to GitHub Actions secrets so the pipeline runner can use them.

variable "tavily_api_key" {
  description = "Tavily API key for web research"
  type        = string
  sensitive   = true
}

variable "anthropic_api_key" {
  description = "Anthropic API key for script generation"
  type        = string
  sensitive   = true
}

variable "elevenlabs_api_key" {
  description = "ElevenLabs API key for TTS synthesis"
  type        = string
  sensitive   = true
}

variable "openai_api_key" {
  description = "OpenAI API key (TTS fallback)"
  type        = string
  sensitive   = true
  default     = ""
}
