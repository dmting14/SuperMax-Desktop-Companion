"""Formula 1 public latest-news HTML listing; this URL is not RSS."""

from news_models import NewsSource

SOURCE = NewsSource("Formula 1", "https://www.formula1.com/en/latest",
                    "formula1.com", 60, 8.0, "F1 官方平台报道", "f1_html")
