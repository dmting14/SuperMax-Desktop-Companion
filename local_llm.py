"""Optional local Ollama summaries. Input is cached source text, never model news recall."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import re
import socket
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from news_models import NewsItem
from news_skill import load_news_skill, validate_skill_result


MODEL = os.environ.get("SUPERMAX_OLLAMA_MODEL", "qwen2.5:1.5b")
OLLAMA_URL = "http://127.0.0.1:11434/api/generate"
MODELS_URL = "http://127.0.0.1:11434/api/tags"


class SummaryError(Exception):
    pass


@dataclass(frozen=True)
class ChineseSummary:
    title: str
    text: str
    model: str
    priority: str = "P1"
    category: str = "other"
    source_status: str = "reported"
    related_to_max: bool = False
    reason: str = ""


def model_available(model: str = MODEL) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.2):
            pass
        with urlopen(MODELS_URL, timeout=1.5) as response:
            names = {entry.get("name") for entry in json.load(response).get("models", [])}
        return model in names
    except (HTTPError, URLError, TimeoutError, OSError, ValueError, TypeError):
        return False


def validate_summary(item: NewsItem, title: str, text: str) -> None:
    if not title or not text or len(title) > 50 or len(text) > 160 or \
            len(re.findall(r"[\u4e00-\u9fff]", text)) > 100:
        raise SummaryError("中文标题或摘要长度不合格")
    if not re.search(r"[\u4e00-\u9fff]", title) or not re.search(r"[\u4e00-\u9fff]", text):
        raise SummaryError("标题或摘要缺少中文内容")
    source = " ".join((item.title, item.body, item.summary, item.decision))
    generated = title + " " + text
    source_numbers = set(re.findall(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?![A-Za-z0-9])", source))
    generated_numbers = set(re.findall(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?(?![A-Za-z0-9])", generated))
    if generated_numbers - source_numbers:
        raise SummaryError("摘要出现原文没有的数字")
    agreement = re.search(r"(\d+) year agreement", item.title, re.I)
    if agreement and agreement.group(1) not in generated_numbers:
        raise SummaryError("摘要遗漏标题中的协议年限")
    if item.driver:
        surname = item.driver.split()[-1]
        if surname.lower() not in generated.lower():
            raise SummaryError("摘要未保留原文车手姓名")
    if item.document_status in ("investigation", "no_action", "withdrawn"):
        if re.search(r"已受罚|被处罚|罚时|罚退|已判罚|遭禁赛|处以罚款", generated):
            raise SummaryError("调查或无处罚文件被写成实际处罚")
    if item.document_status == "penalty" and not re.search(
            r"处罚|警告|罚时|罚退|罚款|处分|降\d+.{0,4}发车|warning|penalty|reprimand", generated, re.I):
        raise SummaryError("处罚摘要未明确处罚性质")
    if item.document_status == "penalty":
        decision_number = re.search(r"(?:Drop of|penalty of) (\d+) grid", item.decision, re.I)
        if decision_number and decision_number.group(1) not in generated_numbers:
            raise SummaryError("摘要未保留裁决中的处罚位数")
    if re.search(r"grid (?:position|place|penalt)|grid drop", source, re.I) and \
            "罚时" in generated and not re.search(r"time penalt", source, re.I):
        raise SummaryError("发车位处罚被误写为罚时")
    if item.credibility.startswith("媒体") and re.search(r"官方确认|FIA确认|车队正式宣布", generated):
        if not re.search(r"official|confirmed|announc", source, re.I):
            raise SummaryError("媒体消息被升级为官方确认")
    if item.source == "Formula 1" and re.search(r"F1官方.{0,8}(?:处以|处罚|罚退)", generated):
        if not re.search(r"F1 (?:officials? )?(?:imposed|penalized)", source, re.I):
            raise SummaryError("新闻发布平台被误写为处罚机构")
    if re.search(r"\breturns? to Africa\b", source, re.I) and re.search(
            r"首次(?:在|于)非洲|非洲(?:大陆)?首次", generated):
        if not re.search(r"(?:自|从)\d{4}年以来.{0,6}首次", generated):
            raise SummaryError("重返非洲被误写为历史首次举办")


def _evidence(item: NewsItem) -> str:
    if item.document_id:
        drop = re.search(r"Drop of (\d+) grid positions in the next Race", item.decision, re.I)
        if item.document_status == "penalty" and drop:
            return (f"FIA 官方最终裁决：{item.driver}在下一场参加的正赛中"
                    f"罚退{drop.group(1)}个发车位。")
        if item.document_status == "no_action":
            return f"FIA 官方裁决：{item.driver}不采取进一步行动。原文：{item.decision}"
        if item.document_status == "investigation":
            return f"FIA 调查通知，尚无最终处罚。车手：{item.driver}。文件内容：{item.body[:500]}"
        lines = [f"Driver: {item.driver}", f"Decision: {item.decision}"]
        return "\n".join(lines)
    body = item.body or item.summary
    if re.search(r"\breturns? to Africa\b", item.title + " " + body, re.I):
        year = re.search(r"first time since (\d{4})", body, re.I)
        if year:
            agreement = re.search(r"(\d+) year agreement to race in ([A-Za-z]+)", item.title, re.I)
            deal = (f"F1与{agreement.group(2)}达成{agreement.group(1)}年赛事协议，"
                    if agreement else "F1将")
            return f"{deal}自{year.group(1)}年以来首次重返非洲；非洲此前举办过F1赛事。"
    lines = [line.strip() for line in body.splitlines() if line.strip()]
    if len(lines) < 2:
        return body[:900]
    first = lines[0]
    surnames = [name.split()[-1] for name, _ in _protected_names(item)]
    detail = max(lines[1:], key=lambda line: (
        sum(bool(re.search(rf"\b{re.escape(name)}\b", line)) for name in surnames),
        bool(re.search(r"\d|\b(?:one|two|three|four|five|ten|twenty)\b", line, re.I)),
        bool(re.search(r"penalt|decision|confirm|sign|appoint|ban|will", line, re.I)),
        len(line)))
    return (first + "\n" + detail)[:1200]


def _protected_names(item: NewsItem) -> tuple[tuple[str, str], ...]:
    if item.driver:
        return ((item.driver, item.driver),)
    found = []
    for full_name in re.findall(r"\b[A-Z][a-z]+ [A-Z][a-z]+\b", (item.body or "")[:600]):
        surname = full_name.split()[-1]
        if re.search(rf"\b{re.escape(surname)}\b", item.title) and surname not in {
                name.split()[-1] for name, _ in found}:
            found.append((full_name, surname))
    return tuple(found[:6])


def summarize_item(item: NewsItem, model: str = MODEL, timeout: float = 90) -> ChineseSummary:
    if not item.url.startswith("https://") or not (item.body or item.summary):
        raise SummaryError("原文链接或正文不足")
    status = item.document_status or item.credibility
    title_source = item.title
    evidence = _evidence(item)
    protected = _protected_names(item)
    tokens = "甲乙丙丁戊己"
    for index, (full_name, surname) in enumerate(protected):
        token = "车手" + tokens[index]
        for name in (full_name, surname):
            pattern = rf"(?<![A-Za-z]){re.escape(name)}(?![A-Za-z])"
            title_source = re.sub(pattern, token, title_source)
            evidence = re.sub(pattern, token, evidence)
    prompt = (load_news_skill() + "\n把以下已采集的 F1 新闻或 FIA 文件事实转述为简体中文，不添加事实。"
              "只输出规定字段的 JSON，摘要不超过100个汉字。"
              "车手代号原样保留；grid penalty 或 grid positions 译为发车位罚退，绝不译为罚时。"
              "如有 Decision，必须准确保留其中的最终处罚位数；新闻发布平台不是处罚机构。"
              "重返某地不等于历史首次在该地办赛。"
              "调查不能写成处罚，媒体报道不能写成官方确认；信息不足时明确说明。\n"
              f"来源：{item.source}\n可信度/状态：{status}\n原文标题：{title_source}\n"
              f"证据：{evidence}\n简体中文 JSON：")
    payload = json.dumps({"model": model,
                          "system": "你是严谨的中文 F1 编辑。标题和摘要必须用简体中文；仅车手姓名或专有名词可以保留英文。",
                          "prompt": prompt, "format": "json",
                          "stream": False, "options": {"temperature": 0.1, "num_ctx": 4096}},
                         ensure_ascii=False).encode("utf-8")
    request = Request(OLLAMA_URL, data=payload,
                      headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout) as response:
            outer = json.load(response)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
        raise SummaryError(f"本地 Ollama 不可用或推理超时：{exc}") from exc
    try:
        result = json.loads(outer["response"])
        title = str(result["title"]).strip()
        text = str(result.get("summary_zh", result.get("summary", ""))).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise SummaryError("模型未返回合规的 JSON 标题和摘要") from exc
    for index, (_, surname) in enumerate(protected):
        token = "车手" + tokens[index]
        title = title.replace(token, surname)
        text = text.replace(token, surname)
    validate_summary(item, title, text)
    try:
        priority, category, source_status, related, reason = validate_skill_result(item, result)
    except ValueError as exc:
        raise SummaryError(str(exc)) from exc
    return ChineseSummary(title, text, model, priority, category, source_status, related, reason)
