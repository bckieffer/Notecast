import os
from pathlib import Path

import boto3


def upload_episode(local_path: Path) -> str:
    """Upload an MP3 to S3 and return its public URL."""
    bucket = os.environ["AWS_S3_BUCKET"]
    base_url = os.environ["PODCAST_FEED_BASE_URL"].rstrip("/")

    key = f"episodes/{local_path.name}"

    s3 = boto3.client("s3")
    s3.upload_file(
        str(local_path),
        bucket,
        key,
        ExtraArgs={"ContentType": "audio/mpeg"},
    )

    return f"{base_url}/{key}"
