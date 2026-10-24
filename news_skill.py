"""Load the project news policy and validate its structured model fields."""

from __future__ import annotations

from pathlib import Path
import re

from news_models import NewsItem


SKILL_PATH = Path(__file__).resolve().parent / "skills" / "f1_news" / "SKILL.md"
PRIORITIES = {"P0", "P1", "P2"}
SOURCE_STATUSES = {"official", "reported", "unconfirmed"}


def load_news_skill() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def validate_skill_result(item: NewsItem, result: dict) -> tuple[str, str, str, bool, str]:
    priority = result.get("priority")
    category = result.get("category")
    status = result.get("source_status")
    related = result.get("related_to_max")
    reason = result.get("reason")
    if priority not in PRIORITIES or status not in SOURCE_STATUSES or not isinstance(related, bool):
        raise ValueError("Skill 优先级、来源状态或关联字段不合格")
    if not isinstance(category, str) or not category.strip() or not isinstance(reason, str) or not reason.strip():
        raise ValueError("Skill 分类或理由缺失")
    if len(category) > 40 or len(reason) > 100:
        raise ValueError("Skill 分类或理由过长")
    if item.credibility.startswith(("媒体", "F1 官方平台报道")) and status == "official":
        raise ValueError("媒体报道不能标为官方确认")
    if item.document_status == "investigation" and category == "penalty":
        raise ValueError("FIA 调查不能标为处罚")
    evidence = " ".join((item.title, item.body, item.summary, item.driver))
    max_named = bool(re.search(r"\b(?:Max Verstappen|Verstappen)\b", evidence, re.I))
    if related and not max_named:
        raise ValueError("原文未提及 Max Verstappen，不能标为与 Max 相关")
    if priority == "P0" and not (max_named or re.search(r"\bRed Bull\b", evidence, re.I)):
        raise ValueError("P0 缺少 Max 或 Red Bull 的原文依据")
    return priority, category.strip(), status, related, reason.strip()
