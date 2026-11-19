# 模型提供方

设置里的「模型提供方」管理国内模型、国际模型、聚合路由和本地服务。没有给角色分配带密钥的模型时，对话和建模仍走离线规则，不会访问网络。

密钥用 Fernet 加密存在本机数据目录，界面只显示末四位。每个提供方可以单独改地址、超时和代理。代理支持 `http://`、`https://` 和 `socks5://`（SOCKS 需要随包的 socksio），并且只作用于这一家，不读取进程的 `HTTP_PROXY`。

## 协议

| 协议 | 用在 | 工具调用 | JSON |
| --- | --- | --- | --- |
| OpenAI Chat Completions | 大多数国内厂商、xAI、Mistral、Groq、Perplexity、聚合器、Ollama、LM Studio、vLLM、自建网关 | `tools` / `tool_calls`，参数统一成 `{id, name, arguments}` | `response_format`。接口拒绝时去掉该字段再抽一次 JSON |
| OpenAI Responses | OpenAI 上把接口风格改成 Responses | `function_call` | `text.format` |
| Anthropic Messages | Claude 原生接口，`x-api-key` 与 `anthropic-version: 2023-06-01` | `tool_use` / `tool_result` | 提示词约束，再从正文抽取 JSON |
| Gemini `generateContent` | Google 原生接口，密钥同时放在 `key` 和 `x-goog-api-key` | `functionDeclarations` / `functionCall` | `responseMimeType` 与 `responseSchema` |
| Cohere v2 | 协议设为 `cohere` 时。预置的 Cohere 走兼容端点，因此归在 OpenAI | v2 `tool_call` | `response_format` |
| Bedrock Converse | AWS SigV4，服务名 `bedrock`，标准库签名，不依赖 botocore | `toolUse` | 提示词约束 |

Azure OpenAI 的模型栏是部署名，地址形如 `https://{resource}.openai.azure.com`，密钥放在 `api-key`，`api-version` 默认 `2024-10-21`。

Bedrock 默认用 Access Key、Secret Key、可选 Session Token 和区域调用 Converse。如果凭证在别处终结，把模式改成 OpenAI 兼容网关（LiteLLM 或 Bedrock Access Gateway），填写网关地址和 Bearer 密钥。

火山方舟的模型 ID 是控制台接入点（`ep-` 开头）。星火走 HTTP 兼容接口，不是旧版 WebSocket。千帆 v2 用 API Key，不是旧版 AK/SK。MiniMax 国内默认 `https://api.minimaxi.com/v1`，国际站是 `https://api.minimax.io/v1`。

Cohere 预置地址是 `https://api.cohere.ai/compatibility/v1`，这样工具调用和别的兼容接口同一套结构。

## 角色

规划、建模、求解顾问、校验、报告各有一条最多三跳的链。前一跳失败才试下一跳。打开并行竞赛后，最多同时问三家，优先采用带工具调用的结果，否则采用更快的成功结果。

规划角色的第一跳会同步到原来的 `llm.provider` / `llm.base_url` / `llm.model`，状态栏和旧的测试入口因此看到同一家。建模角色交给编排器写 AML；规划角色交给对话。链是空的时候，这两处仍使用旧设置，默认是离线。

流式输出、429 与 5xx 的重试（最多 3 次，遵守 `Retry-After`）、超时和用量都记在网关里。用量日志最多 200 条。费用按预设里的公开标价估算，不是账单。模型 ID 会过期，可以用「获取模型」读 `/models`（Bedrock 读 `ListFoundationModels`），也可以手写一条自定义模型。

## 接口

- `GET /api/llm/providers` 分组目录、角色和用量
- `PUT /api/llm/providers/{id}` 启用、地址、模型、代理、超时、额外模型
- `POST /api/llm/providers/{id}/key` 与 `DELETE` 同一路径上的密钥
- `POST /api/llm/providers/{id}/test` 返回延迟和错误
- `POST /api/llm/providers/{id}/models` 拉取模型
- `POST /api/llm/providers` 与 `DELETE /api/llm/providers/{id}` 管理自定义端点
- `PUT /api/llm/roles` 保存角色链
- `POST /api/llm/complete` 按角色做一次规范化补全；`stream: true` 时返回 SSE

`GET/PUT /api/settings` 和 `POST /api/settings/test-llm` 保持原样。

## English

Settings, then Model provider, lists domestic, international, aggregator, and local presets. Offline rules stay in force until a role is pointed at a provider that has a key. Keys are encrypted locally. Protocols are OpenAI Chat Completions and Responses, Anthropic Messages, Gemini generateContent, Cohere v2, and Bedrock Converse signed with SigV4 in the standard library. Bedrock can instead target an OpenAI-compatible gateway. Tool calls are normalized to `{id, name, arguments}`. JSON mode falls back to extracting a JSON value when the endpoint rejects `response_format`. Retries cover 429 and 5xx, honor `Retry-After`, and stop after three attempts. Each provider has its own HTTP or SOCKS proxy. Role chains supply a fallback, and an optional competition fans out to three models. Prices in the usage panel are list-price estimates. Preset model ids go stale; Fetch models and custom models replace them.
