"""Sky Sports public RSS (media, 60-minute cadence)."""

from news_models import NewsSource

SOURCE = NewsSource("Sky Sports", "https://www.skysports.com/rss/12040",
                    "skysports.com", 60, 6.0, "媒体报道")
