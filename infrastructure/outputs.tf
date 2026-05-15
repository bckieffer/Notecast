output "bucket_name" {
  description = "S3 bucket name for episodes and RSS feed"
  value       = aws_s3_bucket.notecast.bucket
}

output "feed_url" {
  description = "Public RSS feed URL — subscribe to this in your podcast app"
  value       = "${local.feed_base_url}/${var.feed_key}"
}

output "github_actions_user_arn" {
  description = "ARN of the IAM user created for GitHub Actions"
  value       = aws_iam_user.github_actions.arn
}
