"""Public FIA Formula 1 steward document listing."""

from fia_documents import SEASON_DOCUMENTS_URL
from news_models import NewsSource

SOURCE = NewsSource("FIA 裁决文件", SEASON_DOCUMENTS_URL, "fia.com", 60, 9.0,
                    "官方文件", "fia_documents")
