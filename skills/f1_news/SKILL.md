---
name: f1-news
description: Evaluate sourced Formula 1 news for SuperMax, assign priority and source status, and produce a concise Chinese summary from supplied evidence.
---

# SuperMax F1 News Skill

只依据传入的原文或 FIA 文件生成结果，不凭模型记忆补充新闻事实。可信度与用户兴趣是两个独立维度。

## 优先级

- P0：Max Verstappen 的判罚或合同、他参与的其他汽车赛事、Red Bull 重大车队变动。
- P1：正式车手签约、离队或加盟；车队关键管理层或技术人员变动；FIA 重大规则或技术调整；赛历重大变化。
- P2：普通赛事新闻、采访、日常车队动态和升级套件。P2 通常不进入重要新闻列表。

忽略未经证实的转会传闻、无来源爆料、杜撰引语、娱乐八卦、重复报道、标题党和没有实质内容的新闻。

FIA 调查不是处罚；撤回、无进一步行动、正式裁决及实际处罚必须分别表述。媒体报道不能写成官方确认。无法核对时写明信息不足。

仅输出 JSON 对象，字段：priority (P0/P1/P2)、category (事件类型)、source_status (official/reported/unconfirmed)、related_to_max (布尔值)、title (中文标题)、summary_zh (不超过100个汉字)、reason (简短筛选理由)。不添加原文没有的日期、数字、人物、车队或处罚。
