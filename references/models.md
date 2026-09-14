# AntSK 模型目录与能力矩阵

数据来源：BigBanana `types/model.ts` 内置模型定义（AntSK provider）。以 `python scripts/antsk.py models` 查询到的实际列表为准。

## 文本 / 剧本模型（/v1/chat/completions）

| 模型 | 定位 | 建议场景 |
|---|---|---|
| `gpt-5.4` | 高性价比稳健 | 剧本拆解、分镜提示词、JSON 结构化输出（默认） |
| `gpt-5.6-terra` | 均衡，成本约为 5.5 一半 | 日常主力 |
| `gpt-5.6-sol` / `gpt-5.5` | 旗舰 | 复杂长篇、强推理 |
| `gpt-5.2` / `gpt-5.1` | 前沿/旗舰通用 | 长文本分析、结构化提取 |
| `claude-sonnet-4-6` | 速度与智能平衡 | agent 场景 |
| `claude-opus-4-8` / `-4-7` / `-4-6` | Claude 顶级 | 高质量优先 |
| `gemini-3.1-pro-preview` | 多模态长上下文 | 文档理解、研究分析 |

## 图片模型

| 模型 | 协议 | 特点 |
|---|---|---|
| `gemini-3-pro-image-preview` (Nano Banana Pro) | Gemini `:generateContent` | 旗舰画质、复杂构图、参考图一致性最强；角色/场景/道具首选 |
| `gemini-3.1-flash-image-preview` (Nano Banana 2) | Gemini | 与 Pro 价格一致，一般直接用 Pro |
| `gpt-image-2` / `gpt-image-1.5` | OpenAI `/v1/images/generations` | 提示词遵循与文字渲染优秀；参考一致性弱于 Banana Pro（脚本自动切换 edits 协议传参考图） |
| `seedream-5.0` / `seedream-4.6` | OpenAI-compatible `/v1/images/generations` | AntSK 字节系图片模型；支持多候选图，参考图走 edits 协议 |

参考图上限：Gemini 系约 14 张；OpenAI 系约 16 张。

## 视频模型（/v1/videos 异步任务）

| 模型 | 时长(秒) | 首帧 | 尾帧 | 多参考图 | 真人 | 备注 |
|---|---|---|---|---|---|---|
| `sora-2` | 4-12（整数） | ✅ | ❌ | ❌ | ❌ | 最便宜（约 0.1$/s），动画效果好；唯一支持 1:1 |
| `veo_3_1-fast` | 4/6/8 | ✅ | ✅ | ❌ | ✅ | 首尾帧插值；稳定性一般 |
| `gemini-omni-flash` | 3-10 | ✅ | ✅(仅frame模式) | ✅(≤4) | ❌ | 按次计费（约 0.8$）；多图需 reference_mode=reference |
| `doubao-seedance-1-5-pro` | 4-12（整数） | ✅ | ✅ | ❌ | ✅ | 约 0.3$/s；挂载 SORA 参数，唯一另一个支持 1:1 的模型 |
| `doubao-seedance-2-0-mini` | 5-15 | ✅ | — | ✅(≤4) | ❌ | 约 0.6$/s |
| `doubao-seedance-2-0-fast` | 5-15 | ✅ | — | ✅(≤4) | ❌ | 约 1$/s，性价比高 |
| `doubao-seedance-2-0` | 5-15 | ✅ | — | ✅(≤4) | ❌ | 约 1.5$/s，最强质量 |
| `doubao-seedance-2-5` | 5-15 | ✅ | — | ✅(≤4) | ❌ | AntSK 多参考图异步模型，能力对齐 Seedance 2.0 |
| `happyhorse-1.0` / `-1.1` | 5-15 | ✅ | — | ✅(≤4) | ✅ | 约 1.5$/s，昂贵 |
| `bigbanana-2.0-fast-cheep` | 5-15 | ✅ | — | ✅(≤4) | ❌ | JSON images 载荷，能力对齐 Seedance 2.0 Fast |
| `viduq3-turbo` | 5-16 | ✅ | ✅ | ❌ | ✅ | JSON 载荷，必须首帧；按次计费，质量优先 |
| `viduq3-pro` | 5-16 | ✅ | ✅ | ❌ | ✅ | JSON 载荷，必须首帧；按次计费，价格非常高，关键镜头用 |

说明：
- 多参考图模型（doubao-2.0 / happyhorse / gemini-omni reference 模式）需要用紧凑 `@1：说明` 语法标注每张参考图用途，脚本 `--annotation` 参数会自动注入。
- `bigbanana-2.0-fast-cheep` 使用 JSON images 载荷（脚本已处理），一般无需直接使用。
- 不支持真人的模型收到真人内容请求会失败或被风控：选 `veo_3_1-fast`、`viduq3-*`、`happyhorse-*`。

## BigBanana 中存在、但不经 AntSK 的视频模型（本 skill 不覆盖）

以下内置模型在 BigBanana 源码（types/model.ts）中挂载在独立 provider 下，需要各自的官方 API Key，
无法用 AntSK 令牌调用，因此本 skill 不实现：

| 模型 | provider | 端点 | 说明 |
| --- | --- | --- | --- |
| `doubao-seedance-1-5-pro-251215` | volcengine（ark.cn-beijing.volces.com） | `/api/v3/contents/generations/tasks` | 火山引擎任务模式，首帧/首尾帧，5-15s |
| `doubao-seedance-2-0-fast-260128` | volcengine | `/api/v3/contents/generations/tasks` | reference_image 多参考图，5-15s，不支持真人 |
| `doubao-seedance-2-0-260128` | volcengine | `/api/v3/contents/generations/tasks` | reference_image 多参考图，5-15s，不支持真人 |
| `viduq2-pro` | vidu（api.vidu.cn） | `/ent/v2/reference2video` | Vidu 官方直连；AntSK 版 viduq2 已从内置模型移除 |
| `viduq3-turbo` / `viduq3-pro`（直连版） | vidu | `/ent/v2/img2video` | AntSK 用户请用上表 `viduq3-*`（/v1/videos 桥接） |

## 语音模型（/v1/chat/completions + modalities）

| 模型 | 特点 |
|---|---|
| `gpt-audio-1.5` | 高质量配音，情绪表达好（默认） |
| `gpt-audio-mini` | 轻量快速，适合批量草稿 |

音色（voice）：`alloy`（默认）、`ash`、`ballad`、`coral`、`echo`、`fable`、`nova`、`onyx`、`sage`、`shimmer`、`verse`。

## 默认激活组合（与 BigBanana 一致）

chat=`gpt-5.4`，image=`gemini-3-pro-image-preview`，video=`sora-2`，audio=`gpt-audio-1.5`。
