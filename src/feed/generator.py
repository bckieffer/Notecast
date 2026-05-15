"""
RSS feed generator.

Maintains a feed_state.json in S3 as the source of truth for all episodes,
then regenerates podcast.xml from scratch on each update. This avoids XML
parsing and ensures the feed is always well-formed.
"""

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError
from feedgen.feed import FeedGenerator

_FEED_STATE_KEY = "feed_state.json"


@dataclass
class Episode:
    guid: str
    title: str
    description: str
    url: str
    pub_date: str   # ISO 8601 with timezone, e.g. "2026-05-15T14:30:00+00:00"
    file_size: int  # bytes
    duration: int   # seconds


def update_feed(episode: Episode, config: dict) -> str:
    """Add episode to the feed and regenerate podcast.xml. Returns the feed URL."""
    bucket = os.environ["AWS_S3_BUCKET"]
    feed_key = os.environ.get("AWS_S3_FEED_KEY", "podcast.xml")
    base_url = os.environ["PODCAST_FEED_BASE_URL"].rstrip("/")

    s3 = boto3.client("s3")

    episodes = _load_state(s3, bucket)
    episodes.append(asdict(episode))
    _save_state(s3, bucket, episodes)

    xml_bytes = _generate_xml(episodes, config, base_url, feed_key)
    s3.put_object(
        Bucket=bucket,
        Key=feed_key,
        Body=xml_bytes,
        ContentType="application/rss+xml",
    )

    return f"{base_url}/{feed_key}"


def _load_state(s3, bucket: str) -> list[dict]:
    try:
        obj = s3.get_object(Bucket=bucket, Key=_FEED_STATE_KEY)
        return json.loads(obj["Body"].read())
    except ClientError as e:
        if e.response["Error"]["Code"] in ("NoSuchKey", "404"):
            return []
        raise


def _save_state(s3, bucket: str, episodes: list[dict]) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=_FEED_STATE_KEY,
        Body=json.dumps(episodes, indent=2).encode(),
        ContentType="application/json",
    )


def _generate_xml(
    episodes: list[dict],
    config: dict,
    base_url: str,
    feed_key: str,
) -> bytes:
    feed_url = f"{base_url}/{feed_key}"

    fg = FeedGenerator()
    fg.load_extension("podcast")

    fg.id(feed_url)
    fg.title(config.get("podcast_name", "Notecast"))
    fg.description(config.get("podcast_tagline", "AI-generated research episodes"))
    fg.link(href=feed_url, rel="self")
    fg.language("en")
    fg.podcast.itunes_explicit("no")
    fg.podcast.itunes_author(config.get("podcast_name", "Notecast"))
    fg.podcast.itunes_category("Technology")

    for ep in sorted(episodes, key=lambda e: e["pub_date"], reverse=True):
        fe = fg.add_entry()
        fe.id(ep["guid"])
        fe.title(ep["title"])
        fe.description(ep["description"])
        fe.enclosure(url=ep["url"], length=str(ep["file_size"]), type="audio/mpeg")
        fe.published(ep["pub_date"])
        fe.podcast.itunes_duration(ep.get("duration", 0))

    return fg.rss_str(pretty=True)
