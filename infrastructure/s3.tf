resource "aws_s3_bucket" "notecast" {
  bucket = var.bucket_name

  tags = {
    Project = "notecast"
  }
}

# Episodes and the RSS feed must be publicly readable so podcast apps can
# subscribe without authentication. Access is "private by obscurity" — no
# bucket listing is granted, only object-level GET.
resource "aws_s3_bucket_public_access_block" "notecast" {
  bucket = aws_s3_bucket.notecast.id

  block_public_acls       = false
  block_public_policy     = false
  ignore_public_acls      = false
  restrict_public_buckets = false
}

resource "aws_s3_bucket_policy" "notecast" {
  bucket = aws_s3_bucket.notecast.id

  # depends_on ensures the public access block is removed before the policy is applied
  depends_on = [aws_s3_bucket_public_access_block.notecast]

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "PublicReadObjects"
        Effect    = "Allow"
        Principal = "*"
        Action    = "s3:GetObject"
        Resource  = "${aws_s3_bucket.notecast.arn}/*"
      }
    ]
  })
}

resource "aws_s3_bucket_cors_configuration" "notecast" {
  bucket = aws_s3_bucket.notecast.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["*"]
    max_age_seconds = 3600
  }
}
