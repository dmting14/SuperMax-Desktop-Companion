# SuperMax

SuperMax 是一个面向 Windows 的 F1 主题桌面小组件，为个人兴趣开发。PySide6 透明窗口播放角色动画，五个轮胎入口分别打开赛历、赛果、新闻、To-Do 和番茄钟。公开版默认使用项目原创、程序化生成的火柴人；私人角色素材还原了一些二创中的建模形象，为不产生侵权，这些角色素材不在仓库中，动画演示用最简单的火柴人骨架代替，实际形象为3的建模，并配有多种动画。

![公开版实际 Qt 界面：火柴人、轮胎导航和番茄钟](docs/screenshots/public-pomodoro.png)

截图由运行中的 PySide6 窗口部件在 offscreen 模式下捕获并按实际上下位置合成；使用公开角色和空的临时 SQLite 数据库，没有填入模拟赛况。[更多界面截图与演示建议](docs/DEMO.md)。

## 已实现

- 透明桌宠、24 FPS 动画、拖动、五轮胎导航及折叠面板。
- Jolpica 赛历、正赛倒计时、上一站领奖台及前五名积分榜；SQLite 赛事实时缓存，打开页面先显示缓存。
- FIA、Formula 1、Sky Sports F1 等公开来源的新闻采集、筛选、来源退避和 SQLite 缓存；新闻原文链接、点赞/点踩持久化及轻量排序。
- 可选本机 Ollama / Qwen 中文摘要：Python 读取 `skills/f1_news/SKILL.md`，传给模型并校验结构化结果；模型不可用或输出不合格时保留原文信息。
- 本地 SQLite 四象限任务与 25 分钟番茄钟。

## 技术与结构

Python 3.10、PySide6 Essentials、pypdf、SQLite（Python 标准库）；新闻网络请求由工作线程执行，LLM 仅连接本机 Ollama。没有云端模型依赖。

| 模块 | 职责 |
| --- | --- |
| `main.py`, `animation.py`, `public_assets/` | Qt 入口、动画播放、原创公开帧与生成器 |
| `demo_ui.py`, `ui_icons.py` | 五页界面、交互、Qt 工作线程与定时器 |
| `f1_data.py`, `race_store.py` | 赛事接口与 SQLite 赛历/赛果缓存 |
| `news_sources/`, `news_data.py`, `news_articles.py`, `fia_documents.py` | 来源配置、新闻筛选、文章与 FIA 文件解析 |
| `news_service.py`, `news_store.py`, `news_skill.py`, `local_llm.py` | 刷新调度、SQLite、新闻规则及可选 Qwen 摘要 |
| `task_store.py`, `tests/` | 本地任务与离线回归测试 |

## 安装与运行

要求 Windows、Python 3.10 和可用的桌面会话。默认角色无需下载任何图片。在仓库根目录执行：

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py --check
.\.venv\Scripts\python.exe main.py
```

公开版默认 `SUPERMAX_THEME=public`。如拥有**自行授权且未提交到本仓库**的私人动画，可把包含 `animations/manifest.json` 的目录设置为 `SUPERMAX_PRIVATE_ASSETS_ROOT`，并设置 `SUPERMAX_THEME=private`。公开火柴人可用 `.\.venv\Scripts\python.exe public_assets/generate_walk.py` 从源码重新生成。

## 可选本地摘要

安装 Ollama 后可执行 `ollama pull qwen2.5:1.5b`。程序默认检查这个模型名；其他本机模型可通过 `SUPERMAX_OLLAMA_MODEL` 指定。模型权重和个人新闻数据库不会提交。新闻采集与桌宠在没有 Ollama 时仍可运行。模型摘要可能被事实校验拒绝，不能代替人工核对。[真实调用记录](docs/VALIDATION.md)。

新闻与用户反馈存于 `user_data/news.sqlite3`，赛事缓存存于 `user_data/races.sqlite3`，任务存于 `user_data/tasks.sqlite3`；这些文件均被 Git 忽略。来源使用公开页面、RSS 和 FIA 文件，访问稳定性随网络与站点变化。

## 测试与现状

```powershell
.\.venv\Scripts\python.exe -X faulthandler -m unittest discover -s tests -q
.\.venv\Scripts\python.exe main.py --smoke
```

2026-10-24 在 Windows 开发机上，公开目录的 52 项离线测试通过，进程退出码为 0；24 帧的透明通道、循环接缝和 PySide6 播放均有测试。Windows 与 Qt offscreen 的入口启动、新闻刷新中退出及本地 Qwen 调用做过独立进程检查。[验证详情](docs/VALIDATION.md)。

已知问题：曾出现尚未对应到具体故障模块的 Windows 原生访问异常。已复现并修复一种退出时销毁运行中 `QThread` 的问题，也修复了测试页面的延迟销毁；有限回归均正常，但不能据此宣称所有原生异常已根除。外部新闻源可能超时或调整页面结构；部分报道没有可提取的正文，中文摘要会回退。当前视觉资源是公开替代角色，私人 Max 帧、F1/Pirelli 标志和参考图片均未分发。

后续计划：继续收集原生崩溃故障模块证据、提升来源覆盖和摘要事实核验、完善可公开的视觉资源。演示素材与拍摄顺序见 [docs/DEMO.md](docs/DEMO.md)。

本项目是非官方个人作品，与 Formula 1、FIA、Pirelli 或相关车队无关联。仓库只包含原创代码生成图形；Windows 系统字体在本机加载，字体文件不随仓库分发。

仓库的 MIT 许可适用于本项目原创代码、程序化生成的公开角色及其展示截图；不替第三方依赖、外部新闻内容或商标授权。PySide6 Essentials 与 pypdf 由用户自行安装，分别遵循各自的许可证；本仓库不包含它们的代码或安装包。
