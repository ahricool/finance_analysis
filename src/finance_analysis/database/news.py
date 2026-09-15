"""Input record for persisting structured financial news."""

from dataclasses import dataclass


@dataclass
class NewsItem:
    title: str
    snippet: str
    url: str
    source: str
    published_date: str | None = None
