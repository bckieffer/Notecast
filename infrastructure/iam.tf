# Dedicated IAM user for GitHub Actions. Principle of least privilege:
# write access to the notecast bucket only, no other AWS permissions.
#
# Note: the generated secret access key is stored in Terraform state.
# Keep your state file encrypted and access-controlled, or migrate to
# GitHub's OIDC provider (https://docs.github.com/en/actions/security-for-github-actions/security-hardening-your-deployments/configuring-openid-connect-in-amazon-web-services)
# to eliminate long-lived credentials entirely.

resource "aws_iam_user" "github_actions" {
  name = "notecast-github-actions"

  tags = {
    Project = "notecast"
  }
}

resource "aws_iam_user_policy" "github_actions_s3" {
  name = "notecast-s3-access"
  user = aws_iam_user.github_actions.name

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ObjectAccess"
        Effect = "Allow"
        Action = [
          "s3:PutObject",
          "s3:GetObject",
          "s3:DeleteObject",
        ]
        Resource = "${aws_s3_bucket.notecast.arn}/*"
      },
      {
        Sid      = "BucketList"
        Effect   = "Allow"
        Action   = ["s3:ListBucket"]
        Resource = aws_s3_bucket.notecast.arn
      }
    ]
  })
}

resource "aws_iam_access_key" "github_actions" {
  user = aws_iam_user.github_actions.name
}
