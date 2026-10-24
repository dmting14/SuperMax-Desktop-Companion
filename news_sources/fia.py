"""FIA public press release RSS (official, 60-minute cadence)."""

from news_models import NewsSource

SOURCE = NewsSource("FIA", "https://www.fia.com/rss/press-release",
                    "fia.com", 60, 7.0, "官方发布")
