# 验证记录（2026-10-24）

- 从全新 `.venv` 安装 `requirements.txt` 后，在独立公开仓库运行 `python -X faulthandler -m unittest discover -s tests -q`：52 项通过，退出码 0。原目录此前 49 项测试通过；新增公开帧的 3 项测试。
- `main.py --check` 在公开目录输出 `walk_right: 24 帧, 24 FPS, 480x760, 透明通道可读`，退出码 0。
- 程序化帧测试检查 24 张 PNG 的尺寸、透明角点与不透明角色像素；首尾动作差异小于四分之一周期的差异，脚底像素保持在同一基线附近。PySide6 真实 `PetWidget` 播放时帧索引前进，窗口关闭后定时器停止。
- 原生崩溃排查：修复前的受控慢新闻任务退出会输出 `QThread: Destroyed while thread ... is still running`，退出码 1。修复后同一 15 秒任务退出码 0，退出时工作线程未运行。Windows 与 offscreen 模式下，最小 Qt、桌宠、面板切换、新闻任务正常完成/中途关闭均以 0 退出。
- 本机真实 Ollama 模型 `qwen2.5:1.5b` 曾对缓存的 FIA Max Verstappen 文件返回经 Python 校验的 `P0 / official / related_to_max=true` 结构化结果；GUI 工作线程中的实际调用也记录 `GUI_OLLAMA P0 official`，退出码 0。另一次模型输出因把“无进一步行动”写成处罚而被 `SummaryError` 拒绝；缺失模型的异常路径以 0 正常收尾。仓库不包含该本地缓存或模型权重，干净克隆不会自动重放真实调用。
- Qt offscreen 可能打印字体目录与 `raise()` 插件警告；这些是测试环境警告，需分别观察断言和进程退出码。原始 `0x30` Windows 访问异常尚未获得故障模块或转储，不能认定彻底解决。
