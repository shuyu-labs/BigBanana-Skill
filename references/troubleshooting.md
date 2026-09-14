# 故障排查

## 初始化 / 令牌

| 现象 | 原因 | 处理 |
|---|---|---|
| `verify` 返回 401 | 令牌错误/过期/复制不全 | 到 api.antsk.cn 重新生成令牌，`antsk.py init --token <新令牌>` |
| `verify` 返回 403 | 令牌分组限制了模型，或令牌被禁用 | 控制台检查令牌"模型限制/分组"设置，建议不限制 |
| `verify` 网络错误 | 代理/防火墙/DNS | 检查网络；必要时 `set-endpoint` 指向可用网关 |
| `/v1/models` 返回空 | 端点不是 AntSK 兼容网关 | 确认 endpoint 为 https://api.antsk.cn |
| `--deep` 失败但 models 通过 | 令牌无 chat 分组权限或余额为 0 | 控制台确认额度与分组 |

## 图片生成

| 现象 | 原因 | 处理 |
|---|---|---|
| HTTP 400 | 提示词风控 / 参考图过多或格式无效 | 改写提示词（去掉敏感词）；参考图减到 ≤4 张重试；确认图片可读 |
| "No image returned" | 模型偶发未产出图 | 直接重试；连续失败换 `gpt-image-2` |
| blockReason: SAFETY/PROHIBITED | 风控拦截 | 重写提示词，移除违规描述 |
| 人物不像参考图 | 参考图未传或顺序混乱 | `--ref` 第一张放最强身份参考；提示词中显式写"面部以参考图1为准" |

## 视频生成

| 现象 | 原因 | 处理 |
|---|---|---|
| 创建任务 400 | 提示词含不安全内容 / 参数越界 | 检查时长是否在模型允许范围（脚本会预校验）；改写提示词 |
| `Invalid type for 'input_reference': expected an object, but got a file` | 当前网关不接受 multipart 文件字段，要求 JSON 对象协议 | skill 会对单首帧自动回退到 `input_reference: {"image_url":"data:..."}`；多参考图请换 Seedance/Gemini reference 模式。不要把此错误误判为风控 |
| 任务 failed | 上游模型失败，看 fail_reason | 换模型重试（如 veo→sora-2）；真人内容勿用 sora/doubao-2.0/gemini-omni |
| 轮询超时（20 分钟） | 上游拥堵 | 用 `status --task <id>` 稍后再查；任务可能仍在跑 |
| 下载 404/超时 | 视频未就绪或链接过期 | 等 1-2 分钟重试 status → download |
| 画面与参考图不符 | 多参考图模型未注入 @N 注释 | 用 `--annotation` 传每张图用途 |

## 语音生成

| 现象 | 原因 | 处理 |
|---|---|---|
| "no audio data" | 模型不支持音频输出 | 只用 `gpt-audio-1.5` / `gpt-audio-mini` |
| 音色报错 | voice 名不在支持列表 | 用常见音色：alloy/nova/echo/... |
| 中文发音怪 | 未指定语言指令 | 保持 `--language 中文`（脚本已内置语气指令） |

## 通用

- 所有脚本自动重试 429/5xx/网络抖动 3 次（指数退避 2s/4s/8s）；仍失败按上表处理。
- Windows 控制台乱码：脚本已强制 UTF-8 输出；若仍乱码，`chcp 65001` 后重跑。
- 查令牌实际可用模型：`python scripts/antsk.py models --type video`。
- 完全重置：删除 `~/.bigbanana/config.json` 后重新 init。
