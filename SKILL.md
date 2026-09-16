---
name: bigbanana
description: |
  用 AntSK 完成短剧/漫剧的剧本、分镜、角色/场景/道具资产、首帧、视频和配音生产。
  当用户要求写漫剧、拆分镜、生成角色图/场景图/视频/配音或制作 AI 短剧时使用。
---

# BigBanana 漫剧生产技能

## 目标

把创意转成可审核、可续跑、可导出的视觉生产项目。核心原则是**关键帧驱动**：先用角色/场景/道具参考图生成稳定首帧，再用连续动作提示词生成视频。

成功标准：剧本可拍摄，首帧构图明确，视频提示词描述连续动作，镜头之间角色和场景保持一致，所有付费批量生成可恢复且可追踪。

## 入口门禁

第一次执行任何远程生成前先运行：

```bash
python <skill_dir>/scripts/antsk.py status
```

未初始化时，指导用户在 `https://api.antsk.cn` 创建令牌，然后执行 `antsk.py init --token ...` 和 `antsk.py verify`。令牌只能保存在 `~/.bigbanana/config.json`，不能写入项目、日志或回答。详细错误处理见 [troubleshooting.md](references/troubleshooting.md)。

## 标准流程

1. **剧本**：创意 → 结构化剧本；先让用户审核剧情、角色、镜头数和预计时长。剧本 JSON 的 characters / scenes / props 每个元素必须带稳定 `id`（scene_01 等），shots 用 id 引用场景与角色——导演流水线按 id 做归属校验，只有 name 会导致校验全部失败。
2. **导演分镜（推荐）**：`director` 命令跑四阶段流水线——节拍抽取 → 镜头预算 → 分场景镜头扩写 → 质检修订（含对白逐字保留、说话者绑定、连续性状态、道具时序、质量报告）。输出与项目 schema 兼容的 shots（含 start_frame_prompt / video_prompt），直接接后续生成。
3. **视觉设定**：生成角色定妆照、场景图、道具图；为实体保留稳定 ID。
4. **镜头设计**：不用导演流水线时，用 `shot-prompts` 生成首帧提示词和视频动作提示词；构图不写运镜，视频提示词不重复静态外观。
5. **构图选择**：不确定机位时先生成九宫格，人工选择 panel 后生成首帧。
6. **生成**：首帧必须绑定当前镜头的角色/场景/道具参考图；模型支持时可绑定尾帧。
7. **配音与交付**：生成旁白/对白，运行离线质量检查，再导出素材包、字幕和成片。

## 步骤确认门禁（强制）

标准流程的每一步都是独立确认点，**完成一步后必须停下，展示本步产物并取得用户明确确认（如"确认 / 通过 / 下一步"），才能进入下一步**。不允许连续执行多步，也不允许用"如果有问题再告诉我"代替确认：

1. 剧本拆分 → 展示剧本 JSON（剧情、角色、场景、镜头数、时长）
2. 导演分镜 / 镜头设计 → 展示 shots 与质量报告
3. 角色造型 / 场景图 / 道具图 → 逐张展示参考图（含衣橱变体）
4. 首帧（含九宫格选构图）→ 逐镜头展示首帧
5. 视频生成 → 展示逐镜头成片
6. 配音与导出 → 展示最终成片与素材包

任何付费远程生成（图片/视频/配音）在调用前必须先说明要用的模型、生成数量和预计消耗，并取得用户确认；确认后先用 `--max-shots` 验证代表性镜头。`run --approve` 只是付费批量生成的显式门禁，不豁免上述步骤确认。用户对某一步提出修改时，改完重新回到该步的确认点。

## 常用命令

```bash
# 计划、执行、续跑
python scripts/bigbanana_workflow.py plan --idea "..." --out-dir ./episode
python scripts/bigbanana_workflow.py run --out-dir ./episode --approve

# 原子生成
python scripts/bigbanana_generate.py script --idea "..." --out script.json
python scripts/bigbanana_generate.py asset-prompts --script script.json --kind character --out character_prompts.json
python scripts/bigbanana_generate.py shot-prompts --script script.json --out shots.json

# 导演分镜流水线（节拍 -> 预算 -> 分场景扩写 -> 质检修订 -> 质量报告）
# 入口会自动 normalize 补齐缺失 id 并写回 script.json；手改剧本后无需手动补 ID
python scripts/bigbanana_director.py direct --script script.json --source novel.txt \
    --duration 60 --shot-seconds 8 --out director_shots.json --report director_report.json
# 质量报告 dialogueCoverage / beatCoverage / characterBindingRate 未达 100% 时，
# 先按 continuityRisks 修复或重跑，不要带着缺口进入关键帧阶段

# 九宫格和衣橱
python scripts/bigbanana_generate.py grid-prompts --script script.json --shot S01 --out grid_s01.json
python scripts/bigbanana_visual.py grid --grid grid_s01.json --out-dir grid_s01
python scripts/bigbanana_generate.py wardrobe-prompts --script script.json --out wardrobe.json
python scripts/bigbanana_visual.py wardrobe --wardrobe wardrobe.json --out-dir wardrobe_refs

# 质量和导出
python scripts/bigbanana_quality.py assess --project ./episode --out ./episode/quality.json
python scripts/bigbanana_export.py --project ./episode --out ./episode/master.mp4 --subtitles ./episode/subtitles.srt --mix-audio
```

统一入口是 `python scripts/bigbanana.py <generate|workflow|quality|export|visual|image|video|audio|auth> ...`。Agent 集成可使用 `bigbanana_mcp.py` 的离线项目工具；它不能绕过远程生成门禁。

## 按需读取

只在当前任务需要时读取对应参考文件：

- 模型、时长、参考图和真人内容限制：[models.md](references/models.md)
- AntSK 请求协议和兼容层：[api_patterns.md](references/api_patterns.md)
- 首帧、视频和 `@N` 提示词写法：[prompt_methodology.md](references/prompt_methodology.md)
- 项目 schema、实体 ID、manifest 和断点续跑：[project_schema.md](references/project_schema.md)
- 九宫格、衣橱、图像相似度和视觉阈值：[visual_quality.md](references/visual_quality.md)
- plan/run/resume/assess/export/MCP 模式：[workflow_modes.md](references/workflow_modes.md)
- 错误诊断：[troubleshooting.md](references/troubleshooting.md)

## 不变量与边界

- 所有实体和镜头使用 schema version 2 的稳定 ID；旧 JSON 启动时自动迁移。
- 角色参考图优先级最高，镜头不得引用错误角色或无关资产。
- 图片质量检查需要 Pillow；核心 API 脚本仍可只用 Python 标准库运行。
- 视频模型能力必须以脚本内置矩阵或 `antsk.py models` 为准，不手工猜测请求体。
- 远程生成失败时按错误类型处理；不要对风控 400 或未知任务状态盲目重试。
- 视频轮询超时不等于扣费失败，先查询任务状态。
