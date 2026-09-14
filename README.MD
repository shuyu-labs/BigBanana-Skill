# BigBanana-Skill

> 在任意 AI Agent（Codex、Claude、Transwork 等）中复刻 BigBanana AI Director 的短剧 / 漫剧全链路生产能力：
> **剧本策划 → 分镜设计 → 角色·场景·道具图 → 关键帧 → 视频生成 → 语音配音**。
> 全部能力通过 AntSK API 平台（`https://api.antsk.cn`，OpenAI 兼容协议）调用，脚本仅依赖 Python 3.8+ 标准库，无需 `pip install`。

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue)](https://www.python.org/)
[![Dependencies](https://img.shields.io/badge/dependencies-stdlib%20only-brightgreen)]()
[![License](https://img.shields.io/badge/license-see%20repo-lightgrey)]()

---

## 目录

- [这是什么](#这是什么)
- [核心概念：关键帧驱动](#核心概念关键帧驱动)
- [环境要求](#环境要求)
- [快速开始](#快速开始)
- [命令速查](#命令速查)
- [标准工作流](#标准工作流)
- [一键工作流](#一键工作流)
- [模型选择指南](#模型选择指南)
- [目录结构](#目录结构)
- [常见问题](#常见问题)
- [安全与边界](#安全与边界)
- [参考文档](#参考文档)

---

## 这是什么

BigBanana-Skill 是一套**面向 Agent 的影像生产技能包**。它以 `SKILL.md` 作为 Agent 的行为契约，以 `scripts/` 下的 CLI 脚本作为执行层，把 BigBanana 桌面端的生产流程拆解为可被任意 Agent 调用的原子命令。

| 你能做的事 | 对应能力 |
|---|---|
| 把一个创意/小说片段变成结构化剧本与分镜表 | `bigbanana_generate.py` |
| 生成角色定妆照、场景概念图、道具参考图 | `bigbanana_image.py` |
| 用关键帧 + 动作提示词生成视频镜头 | `bigbanana_video.py` |
| 生成旁白与对白配音 | `bigbanana_audio.py` |
| 一条命令跑完整集漫剧 | `bigbanana_workflow.py` |

**与 BigBanana 主程序的关系**：脚本的模型能力矩阵、提示词模板、轮询与重试策略均对齐 BigBanana 源码（`types/model.ts`、`services/ai/*`、`videoModelCapabilities.ts`），因此产出风格与主程序一致，但可脱离桌面端在任意 Agent 环境运行。

---

## 核心概念：关键帧驱动

Text-to-Video 无法精准控制构图与起止画面。本技能遵循 BigBanana 的**关键帧驱动（Keyframe-Driven）**链路：

```
       角色定妆照 / 场景图 / 道具图（参考图，强约束）
                    │
                    ▼
   创意 ──▶ 剧本 JSON ──▶ 分镜提示词 ──▶ 首帧图片 ──▶ 图生视频 ──▶ 成片
                                        （精准构图）   （帧间插值）
```

三条铁律：

1. **先画后动**：首帧提示词只写静态画面（主体 / 环境 / 构图 / 光线 / 风格），**不写运镜**；视频提示词只写镜头内发生的连续动作与节奏。
2. **资产约束**：每个镜头生成画面时必须挂载该镜头涉及的角色定妆照、场景图、道具图作为 `--ref`，并在提示词中指明每张图对应什么，杜绝人物变形与不连戏。
3. **上下文感知**：相邻镜头同场景时，首帧提示词继承上一镜头的光线与机位逻辑，或明确写出转场。

---

## 环境要求

| 项目 | 要求 |
|---|---|
| Python | 3.8 或更高（开发环境 3.11 验证通过） |
| 第三方依赖 | **无**，仅使用标准库（`urllib` / `json` / `base64` / `argparse`） |
| 操作系统 | Windows / macOS / Linux 均可 |
| 网络 | 可访问 `https://api.antsk.cn` |
| 账号 | AntSK API 令牌（`sk-` 开头） |

---

## 快速开始

### 1. 获取 AntSK 令牌

1. 打开 **https://api.antsk.cn** 注册 / 登录；
2. 进入控制台 → **API 令牌（令牌管理）** → **创建令牌**；
3. 建议开启「无限额度」或设置足够额度，**不要限制模型分组**；
4. 复制生成的令牌（`sk-` 开头）。

### 2. 初始化令牌（强制门禁）

任何生成命令执行前必须先初始化。**禁止把令牌硬编码进任何文件。**

```bash
# 查看当前状态
python scripts/antsk.py status

# 保存令牌并自动验证连接
python scripts/antsk.py init --token "sk-xxxxxxxx"

# 深度验证：额外发一次最小 chat 请求（gpt-5.4, max_tokens=5）
python scripts/antsk.py verify --deep
```

初始化成功输出示例：

```
Token saved (sk-abc****1234) -> ~/.bigbanana/config.json
Endpoint: https://api.antsk.cn
Verifying connection via GET /v1/models ...
OK: token valid. 128 models available (chat~46, image~9, video~21, audio~4).
Token initialized. This skill is ready to use.
```

令牌保存在本机用户目录 `~/.bigbanana/config.json`，随时可用 `python scripts/antsk.py logout` 删除。
也可通过环境变量覆盖：`ANTSK_API_KEY`（令牌）、`ANTSK_ENDPOINT`（端点）。

### 3. 跑通第一个镜头

```bash
# ① 创意 → 结构化剧本
python scripts/bigbanana_generate.py script \
  --idea "雨夜，一名失忆少女在旧书店发现一本会自己翻页的日记" \
  --duration 90 --style anime --lang 中文 --out script.json

# ② 剧本 → 角色定妆照提示词 → 生成角色图
python scripts/bigbanana_generate.py asset-prompts --script script.json --kind character --out assets_character.json
python scripts/run_assets.py --assets assets_character.json --prefix char

# ③ 剧本 → 分镜提示词 → 生成首帧
python scripts/bigbanana_generate.py shot-prompts --script script.json --out shots.json
python scripts/run_shots.py --shots shots.json --refs-json refs.json

# ④ 首帧 → 视频
python scripts/bigbanana_video.py generate \
  --prompt "少女缓缓抬头，瞳孔收缩；镜头缓慢推近至面部特写；书页无风自动翻动" \
  --out s01.mp4 --model sora-2 --start s01_start.png --seconds 8

# ⑤ 配音
python scripts/bigbanana_audio.py generate \
  --text "那本日记，写的是我明天的死期。" --out s01_vo.wav --voice alloy --mode narration
```

---

## 命令速查

`<skill_dir>` 用本技能目录的绝对路径替换。所有脚本均可加 `-h` 查看完整参数。

### 令牌管理 `scripts/antsk.py`

| 子命令 | 说明 |
|---|---|
| `status` | 查看是否已初始化、端点、令牌掩码、上次验证时间与模型数 |
| `init --token sk-xxx [--endpoint URL]` | 保存令牌并自动执行一次 `/v1/models` 验证 |
| `verify [--deep]` | 验证令牌；`--deep` 额外发一次真实 chat 请求 |
| `models [--type chat\|image\|video\|audio] [--limit N]` | 列出该令牌实际可用的模型 |
| `set-endpoint URL` | 切换 API 端点（自建网关 / 代理场景） |
| `logout` | 删除本机保存的令牌并重置端点 |

### 文本与提示词 `scripts/bigbanana_generate.py`

| 子命令 | 关键参数 | 说明 |
|---|---|---|
| `chat` | `--prompt` | 单次 chat 补全，用于自由文本任务 |
| `script` | `--idea --duration --style --lang --out` | 创意/小说 → 结构化剧本 JSON |
| `asset-prompts` | `--script --kind character\|scene\|prop --out` | 剧本 → 资产图片提示词 |
| `shot-prompts` | `--script --out` | 剧本 → 每镜头首帧提示词 + 视频动作提示词 |

通用参数：`--model`（默认 `gpt-5.4`）、`--temperature`（默认 `0.7`）、`--max-tokens`（默认 `8192`）。
`--style` 支持 `anime` / `2d` / `3d` / `cyberpunk` / `oil` / `real`（或 `live`），也可直接写自由文本风格。

### 图片 `scripts/bigbanana_image.py`

```bash
python scripts/bigbanana_image.py generate \
  --prompt "..." --out char.png \
  --model gemini-3-pro-image-preview \
  --aspect 16:9 \
  --ref char_01.png scene_01.png prop_02.png
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--aspect` | `16:9` | `16:9` / `9:16` / `1:1` |
| `--ref` | 空 | 参考图列表，**第一张为最强身份参考** |
| `--model` | `gemini-3-pro-image-preview` | Gemini 系走 `:generateContent`，OpenAI 系走 `/v1/images/*`，脚本自动切换协议 |

参考图上限：Gemini 系约 **14** 张，OpenAI 系约 **16** 张。

### 视频 `scripts/bigbanana_video.py`

```bash
python scripts/bigbanana_video.py generate \
  --prompt "连续动作描述，不是静态画面" \
  --out s01.mp4 --model sora-2 \
  --start s01_start.png [--end s01_end.png] \
  --seconds 8 --aspect 16:9 \
  [--ref r1.png r2.png] [--annotation "图1用途" "图2用途"] [--quiet]

# 查询异步任务（轮询超时后用）
python scripts/bigbanana_video.py status --task <task_id>
```

脚本内置**模型能力路由**：根据 `--model` 自动决定是否支持尾帧、是否走多参考图数组、是否注入 `@1：` 紧凑注释、使用哪种请求体格式，并对越界时长/宽高比做预校验。请**不要手工拼请求体**。

### 语音 `scripts/bigbanana_audio.py`

```bash
python scripts/bigbanana_audio.py generate \
  --text "..." --out v1.wav \
  --voice alloy --mode narration --format wav --language 中文
```

| 参数 | 默认 | 可选值 |
|---|---|---|
| `--mode` | `narration` | `narration`（旁白）/ `dialogue`（对白） |
| `--voice` | `alloy` | `alloy` `ash` `ballad` `coral` `echo` `fable` `nova` `onyx` `sage` `shimmer` `verse` |
| `--format` | `wav` | `wav` / `mp3` |
| `--model` | `gpt-audio-1.5` | `gpt-audio-1.5` / `gpt-audio-mini` |

### 批量驱动脚本

| 脚本 | 用途 |
|---|---|
| `run_assets.py --assets assets_character.json --prefix char [--aspect] [--model]` | 按资产提示词 JSON 批量出图，输出 `char_01.png`、`char_02.png`… |
| `run_shots.py --shots shots.json [--refs-json refs.json] [--ref ...] [--aspect] [--model]` | 为每个镜头批量生成首帧，输出 `s01_start.png`… |
| `bigbanana_pipeline.py --idea "..." [--execute]` | 端到端串联全流程，默认只出计划（安全闸门），加 `--execute` 才真正生成 |

`run_shots.py` 的 `--refs-json` 接受 `{"S01": ["char_01.png", "scene_01.png"], ...}` 形式的映射，路径相对于 shots JSON 所在目录；不传时使用脚本内置的 S01–S08 演示映射（仅适用于示例项目）。

---

## 标准工作流

按顺序执行，每步产物是下一步输入。**多镜头项目在批量执行前必须先向用户展示计划并确认成本。**

| 步骤 | 动作 | 产物 |
|---|---|---|
| 1 | **剧本策划**：`generate.py script` 把创意/小说转为结构化 JSON（角色、场景、道具、镜头） | `script.json` |
| 2 | **剧本确认**：把拆解结果给用户确认后再进入资产生成 | — |
| 3 | **视觉设定**：先出角色定妆照，再出场景图与道具图 | `char_*.png`、`scene_*.png`、`prop_*.png` |
| 4 | **镜头设计**：`shot-prompts` 产出每镜头首帧提示词 + 视频动作提示词 | `shots.json` |
| 5 | **关键帧生成**：首帧生成时带上该镜头的角色/场景/道具参考图 | `s01_start.png`… |
| 6 | **视频生成**：首帧（可选尾帧）+ 动作提示词调视频模型，4–15 秒/镜头 | `s01.mp4`… |
| 7 | **语音配音**：旁白 `--mode narration`，对白 `--mode dialogue` | `s01_vo.wav`… |
| 8 | **交付**：汇总文件清单与建议拼接顺序 | — |

> 本技能**不做剪辑合成**。如需拼接镜头与音轨，请使用 ffmpeg 等外部工具。

### 剧本 JSON 结构（`script.json`）

```json
{
  "title": "剧名",
  "episode_title": "本集标题",
  "genre": "类型",
  "style": "日式动漫 (Anime)",
  "logline": "一句话故事",
  "characters": [{"name": "", "identity": "", "appearance": "", "personality": ""}],
  "scenes": [{"name": "", "description": "", "time_of_day": "", "atmosphere": ""}],
  "props": [{"name": "", "description": ""}],
  "shots": [
    {
      "shot_id": "S01",
      "scene": "场景名",
      "characters": ["角色名"],
      "props": ["道具名"],
      "action": "画面动作描述",
      "dialogue": "台词，可为空",
      "narration": "旁白，可为空",
      "duration_seconds": 6,
      "camera": "中景，缓慢推近"
    }
  ]
}
```

### 分镜提示词结构（`shots.json`）

```json
{
  "shots": [
    {
      "shot_id": "S01",
      "start_frame_prompt": "风格 + 主体外观 + 场景 + 动作起始瞬间 + 构图/景别/机位 + 光线氛围",
      "video_prompt": "主体连续动作 + 表情变化 + 环境动态 + 运镜 + 节奏 + (可选)台词：xxx"
    }
  ]
}
```

---

## 一键工作流

`bigbanana_workflow.py` 把上述步骤编排为**可续跑的目录产物**，并保留人工审批闸门。

```bash
# 第一步：只生成剧本与计划，审核镜头数与预计视频秒数
python scripts/bigbanana_workflow.py plan \
  --idea "雨夜，一名失忆少女在旧书店发现一本会自己翻页的日记" \
  --out-dir ./episode

# 第二步：审核 plan.json 后执行完整生产
python scripts/bigbanana_workflow.py run \
  --idea "雨夜，一名失忆少女在旧书店发现一本会自己翻页的日记" \
  --out-dir ./episode --approve
```

| 参数 | 默认 | 说明 |
|---|---|---|
| `--idea` / `--script` | — | 二选一：新创意，或复用已有 `script.json` |
| `--out-dir` | `./bigbanana-output` | 输出目录 |
| `--chat-model` | `gpt-5.4` | 剧本与提示词模型 |
| `--image-model` | `gemini-3-pro-image-preview` | 图片模型 |
| `--video-model` | `sora-2` | 视频模型 |
| `--audio-model` | `gpt-audio-1.5` | 配音模型 |
| `--aspect` | `16:9` | `16:9` / `9:16` / `1:1` |
| `--max-shots` | `0`（不限） | 只跑前 N 个镜头，用于小样验证 |
| `--skip-audio` | 关 | 跳过配音 |
| `--voice` / `--audio-format` | `alloy` / `wav` | 配音音色与格式 |
| `--approve` | 关 | **必填**，确认付费批量生成 |

产物目录结构：

```
episode/
├── script.json            # 结构化剧本
├── plan.json              # 镜头数、预计视频秒数、资产统计
├── character_prompts.json # 角色提示词
├── scene_prompts.json     # 场景提示词
├── prop_prompts.json      # 道具提示词
├── character_01_林夏.png   # 角色定妆照
├── scene_01_旧书店.png     # 场景概念图
├── prop_01_日记本.png      # 道具参考图
├── shots.json             # 分镜提示词
├── s01_start.png          # 镜头首帧
├── s01.mp4                # 镜头视频
├── s01_vo.wav             # 镜头配音
└── manifest.json          # 断点续跑清单（已生成文件会被复用）
```

`manifest.json` 让工作流可中断续跑：已存在且非空的产物会被跳过，不会重复计费。

---

## 模型选择指南

完整目录与价格提示见 [`references/models.md`](references/models.md)。用 `python scripts/antsk.py models --type video` 可查询当前令牌实际可用列表。

### 默认激活组合（与 BigBanana 一致）

| 环节 | 默认模型 |
|---|---|
| 文本 / 剧本 | `gpt-5.4` |
| 图片 | `gemini-3-pro-image-preview`（Nano Banana Pro） |
| 视频 | `sora-2` |
| 语音 | `gpt-audio-1.5` |

### 文本模型

- **默认** `gpt-5.4` —— 性价比稳健，适合剧本拆解与 JSON 结构化输出；
- **复杂长篇** `gpt-5.6-sol` / `claude-opus-4-8`；
- **长文档理解** `gemini-3.1-pro-preview`。

### 图片模型

- **首选** `gemini-3-pro-image-preview` —— 参考图一致性最强，角色/场景/道具首选；
- **OpenAI 风格 / 强文字渲染** `gpt-image-2`（脚本自动切换 edits 协议传参考图）；
- **字节系** `seedream-5.0` / `seedream-4.6`。

### 视频模型

| 模型 | 时长(秒) | 首帧 | 尾帧 | 多参考图 | 真人 | 备注 |
|---|---|---|---|---|---|---|
| `sora-2` | 4-12 | ✅ | ❌ | ❌ | ❌ | 最便宜（约 0.1$/s），动画效果好；唯一支持 1:1 |
| `veo_3_1-fast` | 4/6/8 | ✅ | ✅ | ❌ | ✅ | 首尾帧插值 |
| `gemini-omni-flash` | 3-10 | ✅ | ✅(仅 frame 模式) | ✅(≤4) | ❌ | 按次计费（约 0.8$） |
| `doubao-seedance-1-5-pro` | 4-12 | ✅ | ✅ | ❌ | ✅ | 约 0.3$/s；支持 1:1 |
| `doubao-seedance-2-0-fast` | 5-15 | ✅ | — | ✅(≤4) | ❌ | 约 1$/s，性价比高 |
| `doubao-seedance-2-0` | 5-15 | ✅ | — | ✅(≤4) | ❌ | 约 1.5$/s，最强质量 |
| `doubao-seedance-2-5` | 5-15 | ✅ | — | ✅(≤4) | ❌ | 多参考图异步模型 |
| `happyhorse-1.0` / `-1.1` | 5-15 | ✅ | — | ✅(≤4) | ✅ | 约 1.5$/s，昂贵 |
| `viduq3-turbo` / `viduq3-pro` | 5-16 | ✅ | ✅ | ❌ | ✅ | 必须首帧；按次计费 |

**链路选择建议**

- 只有首帧 → 任意模型，`sora-2` 最省成本；
- 有明确起止状态（转场、动作落点）→ `veo_3_1-fast` 首尾帧插值；
- 需要角色 + 场景 + 道具多图约束 → `doubao-seedance-2-0-fast`（脚本自动注入紧凑 `@1：` 注释语法）；
- 真人镜头 → `veo_3_1-fast`、`viduq3-*`、`happyhorse-*`。**`sora-2`、`doubao`、`gemini-omni` 不支持真人内容。**

### 成本控制

视频是主要开销（按秒计费）。批量生成前必须把镜头清单和预计成本告知用户并确认；先为代表性镜头生成 1 条验证风格，通过后再批量。`plan` 子命令会输出 `estimated_video_seconds` 供估算。

---

## 目录结构

```
BigBanana-Skill/
├── SKILL.md                      # Agent 行为契约（技能定义、工作流、决策规则、边界）
├── README.MD                     # 本文件
├── scripts/
│   ├── antsk_client.py           # 共享 HTTP 客户端：令牌解析、重试退避、错误语义
│   ├── antsk.py                  # 令牌管理 CLI（init/verify/status/models/logout）
│   ├── bigbanana_generate.py     # 剧本 / 资产提示词 / 分镜提示词
│   ├── bigbanana_image.py        # 图片生成（Gemini 与 OpenAI 双协议）
│   ├── bigbanana_video.py        # 视频生成（异步任务 + 轮询 + 下载）
│   ├── bigbanana_audio.py        # 语音配音（chat + modalities 音频输出）
│   ├── bigbanana_workflow.py     # 一键工作流（plan / run --approve）
│   ├── bigbanana_pipeline.py     # 端到端管线（默认只出计划）
│   ├── run_assets.py             # 批量资产出图驱动
│   └── run_shots.py              # 批量镜头首帧驱动
└── references/
    ├── models.md                 # 全量模型目录、能力矩阵与价格提示
    ├── api_patterns.md           # AntSK 各端点请求/响应格式
    ├── prompt_methodology.md     # 提示词方法论（关键帧驱动、参考图约束、@N 注释）
    └── troubleshooting.md        # 错误码诊断与处理
```

---

## 常见问题

### 人物不连戏 / 长相不一致

没传角色定妆照作参考图，或参考图带入了错误风格。修复：每镜头强制传 `--ref`，**第一张放最强身份参考**，并在提示词中显式写明「面部以参考图 1 为准」。

### 视频画面是静态的

视频提示词写成了场景描述。修复：动作提示词要写「镜头内发生了什么」——主体动作 + 表情变化 + 环境动态 + 运镜 + 节奏，不要只写外观。

### 参考图应该怎么排序？

顺序即优先级。推荐：`角色定妆照 → 场景图 → 道具图`。多参考图模型（Seedance / happyhorse / gemini-omni reference）还需用 `--annotation` 按相同顺序说明每张图用途，脚本会自动生成 `@1：…` 注释块。

### 报 400 错误

多为提示词风控或参考图过多/格式无效，**不是**硬性参数错误。修复：改写提示词（去掉敏感描述）；参考图减到 ≤4 张重试；确认图片文件可读。

### 报 `Invalid type for 'input_reference': expected an object, but got a file`

这是网关协议不匹配，**不是提示词风控**。脚本在「仅单首帧」场景会自动回退到 JSON `input_reference: {"image_url":"data:..."}` 格式；多参考图请改用 Seedance / Gemini reference 模式。

### 视频任务一直转圈 / 轮询超时

单次任务最长轮询约 30 分钟（与 BigBanana 主程序一致）。超时不代表扣费失败——用 `python scripts/bigbanana_video.py status --task <id>` 稍后再查，任务可能仍在跑。

### 429 / 5xx

脚本自动指数退避重试 3 次（2s / 4s / 8s）。仍失败说明配额耗尽或上游拥堵，稍后再试。

### JSON 解析失败

模型输出了 markdown 围栏。脚本已内置清洗（剥 ```json 围栏、`<think>` 标签、修复中文引号与尾逗号）。仍失败时降低 `--max-tokens` 或换 `gpt-5.4` 重试。

### Windows 控制台中文乱码

脚本已强制 UTF-8 输出。若仍乱码，先执行 `chcp 65001` 再重跑。

更多错误码对照见 [`references/troubleshooting.md`](references/troubleshooting.md)。

---

## 安全与边界

- **令牌安全**：令牌只保存在 `~/.bigbanana/config.json`，不写入项目文件、日志或对话外的任何位置；脚本输出中只显示掩码（如 `sk-abc****1234`）。`logout` 可随时清除。
- **不虚构模型能力**：不确定某模型是否支持某参数时，用 `antsk.py models` 查询实际可用列表，或查 `references/models.md`。
- **内容合规**：遵守平台风控，不生成违规、低俗、真人侵权内容。400 报错多为提示词风控，应改写提示词重试而非硬重试。
- **不做剪辑**：本技能只负责生成素材，不提供剪辑合成能力；拼接请使用 ffmpeg 等外部工具。
- **付费闸门**：批量生成（`workflow run`）必须显式传 `--approve`；`pipeline` 默认只输出计划，加 `--execute` 才执行。

---

## 参考文档

| 文档 | 内容 |
|---|---|
| [`SKILL.md`](SKILL.md) | Agent 行为契约：强制门禁、能力速查、核心工作流、决策规则、交付前检查 |
| [`references/models.md`](references/models.md) | 全量模型目录、能力矩阵与价格提示 |
| [`references/api_patterns.md`](references/api_patterns.md) | AntSK 各端点请求/响应格式（排障与扩展时读） |
| [`references/prompt_methodology.md`](references/prompt_methodology.md) | 提示词方法论：关键帧驱动、参考图约束语法、`@N` 注释 |
| [`references/troubleshooting.md`](references/troubleshooting.md) | 错误码诊断与处理 |
