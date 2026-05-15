# All secrets consumed by .github/workflows/generate.yml.
# AWS credentials are derived from the IAM user created in iam.tf.
# Third-party API keys are passed in via variables.

locals {
  feed_base_url = "https://${aws_s3_bucket.notecast.bucket}.s3.${var.aws_region}.amazonaws.com"
}

resource "github_actions_secret" "aws_access_key_id" {
  repository      = var.github_repo
  secret_name     = "AWS_ACCESS_KEY_ID"
  value = aws_iam_access_key.github_actions.id
}

resource "github_actions_secret" "aws_secret_access_key" {
  repository      = var.github_repo
  secret_name     = "AWS_SECRET_ACCESS_KEY"
  value = aws_iam_access_key.github_actions.secret
}

resource "github_actions_secret" "aws_default_region" {
  repository      = var.github_repo
  secret_name     = "AWS_DEFAULT_REGION"
  value = var.aws_region
}

resource "github_actions_secret" "aws_s3_bucket" {
  repository      = var.github_repo
  secret_name     = "AWS_S3_BUCKET"
  value = aws_s3_bucket.notecast.bucket
}

resource "github_actions_secret" "aws_s3_feed_key" {
  repository      = var.github_repo
  secret_name     = "AWS_S3_FEED_KEY"
  value = var.feed_key
}

resource "github_actions_secret" "podcast_feed_base_url" {
  repository      = var.github_repo
  secret_name     = "PODCAST_FEED_BASE_URL"
  value = local.feed_base_url
}

resource "github_actions_secret" "tavily_api_key" {
  repository      = var.github_repo
  secret_name     = "TAVILY_API_KEY"
  value = var.tavily_api_key
}

resource "github_actions_secret" "anthropic_api_key" {
  repository      = var.github_repo
  secret_name     = "ANTHROPIC_API_KEY"
  value = var.anthropic_api_key
}

resource "github_actions_secret" "elevenlabs_api_key" {
  repository      = var.github_repo
  secret_name     = "ELEVENLABS_API_KEY"
  value = var.elevenlabs_api_key
}

resource "github_actions_secret" "openai_api_key" {
  repository      = var.github_repo
  secret_name     = "OPENAI_API_KEY"
  value = var.openai_api_key
}
