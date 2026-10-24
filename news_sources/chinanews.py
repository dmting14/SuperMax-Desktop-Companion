"""China News Service public sports RSS (domestic, 30-minute cadence)."""

from news_models import NewsSource

SOURCE = NewsSource("中国新闻网", "https://www.chinanews.com.cn/rss/sports.xml",
                    "chinanews.com.cn", 30, 5.0, "媒体报道")
