# AntSK API 端点请求/响应格式

Base URL：`https://api.antsk.cn`。认证：`Authorization: Bearer <token>`。全部为 OpenAI 兼容协议（源自 BigBanana `services/ai/apiCore.ts`、`visualService.ts`、`video/providers/openaiAsyncBase.ts`、`audioService.ts`）。

## 1. 令牌验证

```
GET /v1/models
Authorization: Bearer sk-xxx
→ 200 {"object":"list","data":[{"id":"gpt-5.4",...},...]}
```
401 = 令牌无效。BigBanana 的深度验证再加一次最小 chat 调用（model=gpt-5.4, max_tokens=5, content="Return 1 only."）。

## 2. Chat Completions（文本/剧本/JSON）

```
POST /v1/chat/completions
{
  "model": "gpt-5.4",
  "messages": [{"role":"user","content":"..."}],
  "temperature": 0.7,
  "max_tokens": 8192,
  "stream": false,
  "response_format": {"type":"json_object"}   // 可选；claude/gemini 不支持时去掉并用提示词约束
}
→ {"choices":[{"message":{"content":"..."}}]}
```
JSON 输出清洗：剥 ```json 围栏、<think> 标签，提取首个平衡的 {...} 块，修复中文引号/尾逗号后再 parse。

## 3a. 图片 — Gemini 协议

```
POST /v1beta/models/gemini-3-pro-image-preview:generateContent
{
  "contents": [{"role":"user","parts":[
    {"text":"<提示词>"},
    {"inlineData":{"mimeType":"image/png","data":"<base64 参考图1>"}},
    {"inlineData":{"mimeType":"image/png","data":"<base64 参考图2>"}}
  ]}],
  "generationConfig": {
    "responseModalities": ["TEXT","IMAGE"],
    "imageConfig": {"aspectRatio": "16:9"}
  }
}
→ {"candidates":[{"content":{"parts":[{"inlineData":{"mimeType":"image/png","data":"<base64>"}}]}}]}
```
`promptFeedback.blockReason` 存在 = 风控拦截。

## 3b. 图片 — OpenAI 协议

```
POST /v1/images/generations            （无参考图，JSON）
{ "model":"gpt-image-2", "prompt":"...", "size":"1536x1024", "quality":"high", "n":1, "output_format":"png" }

POST /v1/images/edits                  （带参考图，multipart/form-data）
  model, prompt, size, quality, n + image[]=<文件>（可多个）
→ {"data":[{"b64_json":"<base64>"} | {"url":"https://..."}]}
```
size 映射：16:9→1536x1024，9:16→1024x1536，1:1→1024x1024。

## 4. 视频 — 异步任务（POST /v1/videos）

### 协议选择（重要）

`/v1/videos` 不是所有模型/网关都使用同一种输入协议。AntSK 旧版兼容层通常接受下面的 multipart 文件格式；部分新版网关会返回 `Invalid type for 'input_reference': expected an object, but got a file instead`，此时必须改用 JSON 对象格式。不要把两种格式混在同一个请求里，也不要把 HTTP 400 一律当作提示词风控。

创建（form-data，sora/veo/doubao/gemini-omni 通用）：
```
POST /v1/videos        (multipart/form-data)
  model=sora-2
  prompt=<连续动作描述>
  seconds=8
  size=1280x720            # 16:9→1280x720, 9:16→720x1280, 1:1→720x720
  input_reference=<reference.png>     # 恰好 1 张图时
  input_reference[]=<reference-N.png> # ≥2 张图时逐张追加（首帧/尾帧/参考图统一走数组）
  reference_mode=frame|reference     # gemini-omni 专用（frame 与 reference 模式均携带）
→ {"id":"video_xxx"} 或 {"task_id":"..."}

新版 JSON 对象兼容格式（通常用于单首帧）：
```
POST /v1/videos
{
  "model": "sora-2",
  "prompt": "从首帧开始，人物缓慢抬头并向前走，镜头平稳推近",
  "seconds": 8,
  "size": "1280x720",
  "input_reference": {
    "image_url": "data:image/png;base64,<base64>"
  }
}
```
skill 会先按模型路由发送标准协议；若只收到上述 `input_reference` 类型错误且只有一张参考图，会自动进行一次 JSON 对象回退。多参考图仍应使用支持多图的 Seedance/Gemini reference 模式，不要强行把多张图塞进单对象。
```
参考图注入规则（镜像 openaiAsyncBase）：每个模型固定注入"首帧参考图。"（有尾帧再加"尾帧参考图。"），
`--annotation` 附加在参考图之后；doubao-2.0 多参考模式丢弃尾帧并按图片顺序注入紧凑注释
`@1：说明`（第二行固定为"请严格按照 @编号 理解参考图作用…"）。

创建（JSON images 载荷，仅 bigbanana-2.0-fast-cheep）：
```
POST /v1/videos
{ "model":"...", "prompt":"...", "images":["data:image/png;base64,..."],
  "size":"16*9", "seconds":"10", "width":16, "height":9 }
```
size 分隔符为 `*`，并携带宽高比数字 width/height。

创建（JSON 载荷，viduq3-* / vidu-q3-* 专用）：
```
POST /v1/videos
{ "model":"...", "prompt":"...", "duration":8,
  "images":["data:image/png;base64,..."],
  "metadata": { "resolution":"1080p", "audio":true, "audio_type":"all" } }
```
duration 为数字；必须提供首帧，多余参考图被忽略；viduq3 启用音频。

轮询与下载：
```
GET /v1/videos/{task_id}          → {"status":"queued|running|completed|succeeded|failed|error", ...}
                                     completed 时取 metadata.url→…→url 等嵌套字段，
                                     或解析 videoId（id 以 video_ 开头优先，否则 output_video/video_id/outputs[0].id/id）
GET /v1/videos/{video_id}/content → 直接返回视频字节流（或 JSON 含 url 字段）
```
轮询间隔 5s，总超时 30 分钟；任何非 200 或网络错误都重试直至超时；failed 时取
`error.message` / `error.code` / `message`。下载重试 5 次（间隔 5s×次数）。

## 5. 语音 — Chat Completions 音频输出

```
POST /v1/chat/completions
{
  "model": "gpt-audio-1.5",
  "modalities": ["text","audio"],
  "audio": {"voice":"alloy","format":"wav"},     // 或 mp3
  "messages": [{"role":"user","content":"<语气指令>\n\n<正文>"}],
  "temperature": 0.6
}
→ {"choices":[{"message":{"audio":{"data":"<base64>","transcript":"..."}, "content":"..."}}]}
```

## 6. 通用错误语义

| 状态 | 含义 | 处理 |
|---|---|---|
| 400 | 提示词风控或参数无效 | 改写提示词，不要原样重试 |
| 401 | 令牌无效 | 重新 init |
| 402 | 余额不足 | 充值 |
| 403 | 分组/模型权限 | 检查令牌设置 |
| 429 | 限流 | 退避重试 |
| 500/503 | 上游繁忙 | 退避重试 |
