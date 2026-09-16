# BigBanana 提示词方法论（关键帧驱动）

源自 BigBanana AI Director 的核心生产理念：**先画后动、资产约束、上下文感知**。

## 1. 关键帧驱动（Keyframe-Driven）

Text-to-Video 无法精准控制运镜和起止画面。正确链路是：

```
首帧图片（精准构图） → 图生视频（帧间插值） → 成片
      ↑ 受角色/场景/道具参考图强约束
```

- 首帧提示词：静态画面描写——主体、环境、构图、光线、风格。**不写镜头运动**。
- 视频提示词：动态描写——镜头内发生了什么：主体动作、表情变化、环境动态（风/雨/光斑）、运镜（推/拉/摇/移）、节奏。
- 需要精确落点时提供尾帧（veo/viduq3/gemini-omni 支持首尾帧插值）。

反例（弱）："夜晚的城市街道，霓虹灯闪烁。"
正例（首帧）："雨后夜晚的城市巷口，低角度中景，湿漉漉的柏油路反射红蓝霓虹，一名穿黑色风衣的短发女性背对镜头站在巷口左侧三分之一处，远处路灯昏黄，日式赛博朋克动画风格，电影级打光。"
正例（视频）："女性缓缓转过身面向镜头，表情从警惕转为惊讶；镜头缓慢推近至胸像；霓虹灯光在她脸上明暗交替；雨滴从檐口滴落。台词：'你终于来了。'"

## 2. 资产一致性约束（参考图体系）

每个镜头的画面生成都要挂参考图，并显式说明每张图的角色：

```
参考图角色标注（发提示词时随图注入）：
- 图1：主角"林夏"定妆照 —— 面部/发型/服装以此为准
- 图2：场景"老宅阁楼"概念图 —— 空间布局与光线逻辑以此为准
- 图3：道具"青铜罗盘" —— 形状材质以此为准
```

一致性规则（BigBanana 内置规则，转述给图像模型）：
- 角色一致性：生成的角色必须与参考图完全一致（脸、发型、体型、服装细节）；不同角色的参考绝不能融合。
- 场景一致性：严格保持场景布局、氛围、光线逻辑。
- 道具一致性：形状、材质、颜色、细节与参考一致。
- 三视图（3x3 turnaround）：用于锁定多角度角色一致性，优先取与当前机位匹配的面板。

## 3. 多参考图 @N 注释语法（视频模型）

doubao-seedance-2.0 / happyhorse / gemini-omni(reference) 等多图模型用：

```
@1：主角林夏定妆照，面部与服装以此为准
@2：老宅阁楼场景图，空间与光线以此为准

请严格按照 @编号 理解参考图作用。若提供首帧，则默认 @1 为首帧/起始构图，后续图片为场景、角色、道具等参考图。请保持各参考图对应的主体、物件、空间关系和身份边界清晰，不要混淆。
<视频动作提示词正文>
```

脚本 `--annotation "说明1" "说明2"` 按 `--ref` 顺序自动生成此块。

## 4. 镜头提示词模板（shot-prompts 的输出契约）

每个镜头两个提示词：

```json
{
  "shot_id": "S01",
  "start_frame_prompt": "风格 + 主体外观(引角色特征) + 场景 + 动作起始瞬间 + 构图/景别/机位 + 光线氛围",
  "video_prompt": "主体连续动作 + 表情变化 + 环境动态 + 运镜 + 节奏 + (可选)台词：xxx"
}
```

## 5. 风格关键词库

| 风格 | 关键词（拼入提示词） |
|---|---|
| anime | Japanese anime style, cel shading, clean line art, vibrant colors |
| 2d-animation | 2D flat animation style, bold outlines, limited palette |
| 3d-animation | 3D CGI animation style, Pixar-like rendering, soft global illumination |
| cyberpunk | cyberpunk style, neon lighting, high contrast, rain-slicked streets |
| oil | oil painting style, visible brush strokes, rich textures |
| real (live action) | photorealistic, cinematic film still, 35mm, shallow depth of field |

通用收尾：`cinematic lighting, high detail, no text overlays`（负向：`text, watermark, deformed hands, extra fingers`）。

## 6. 剧本→镜头的拆分标准

- 每镜头 4-10 秒；一个镜头一个完整动作单元（不要一句话拆两半）。
- 叙事闭环：3 秒内钩子 → 冲突升级 → 转折 → 结尾悬念（连续剧）或收束（单集）。
- 场景连续性：相邻镜头同场景时，首帧提示词必须继承上一镜头的光线与机位逻辑，或明确写出转场。
- 台词与口型：video_prompt 末尾附"台词：xxx"，配音用 dialogue 模式；旁白用 narration 模式独立生成。

## 7. 导演流水线（bigbanana_director.py，源自 AI-Director directorAgentService）

`script` + `shot-prompts` 是两步一次性生成；导演流水线把拆分升级为可质检的闭环：

```
原文（分块 12k 字符，跨块携带出口状态）
  → ① 剧本分析：dialogueLines（逐字台词+说话者） + storyBeats（节拍）
  → ② 节拍规划：每场镜头预算（仅参考值）
  → ③ 分场景镜头扩写：动作 + 对白绑定 + 连续性进出状态 + 首尾帧提示词
  → ④ 质检修订（≤2 轮）：issues+patch → 规则复检 → 质量报告
```

核心概念：

- **节拍（beat）**：叙事最小单元，purpose ∈ setup / conflict / escalation / reaction / result / hook；
  每拍带 sourceText（原文依据）与 entryState / exitState（连续性进出状态）。
- **对白逐字保留**：台词不得概括删改；每镜一个说话者；旁白/画外音单独识别；
  模型漏掉的台词从原文正则兜底恢复（`角色：台词` 与引号对白）。
- **镜头预算是软约束**：关键动作、道具状态变化、对白后的反应、结尾钩子必须独立成镜；纯过渡可合并。
- **节拍覆盖对齐是单调的**：后一镜不能偷取前一号节拍（集合式分配会打断闪回证据链和道具交接）；
  缺拍时本地补一枚 fallback 镜头而不是丢弃整轮结果。
- **角色解析不做子串猜测**：`小林` 不能绑到 `林`；解析不了的名字必须报错修复，不许猜成别的资产。
- **道具时序**：道具最早出现在其首次出现的节拍；更早镜头上的绑定会被剥掉（宁可少绑，不可穿越）。
- **质量报告**：dialogueCoverage（对白覆盖率）/ beatCoverage（节拍覆盖率）/ characterBindingRate（角色绑定率）
  / duplicateShotCount / continuityRisks / score（25/25/25/15/10 加权）。
  三项覆盖未满 100% 或存在 duplicate 时不进入关键帧阶段。

规则检查与修订补丁在本地代码执行，不信任模型自评：patch 只接受非空字段、beatId 必须同场景、
改动作必须同步首尾关键帧，空占位字段不能抹掉已写好的台词或视觉状态。
