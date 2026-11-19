"""Built-in model providers.

Presets cover Chinese domestic vendors, international APIs, aggregators, and
local OpenAI-compatible servers. Prices are public-list estimates in USD per
million tokens, not invoices. Model ids are the vendor's API names; Fetch
models and custom models replace them when a vendor renames a snapshot.
"""

from __future__ import annotations

from dataclasses import dataclass

GROUPS = ("domestic", "international", "aggregator", "local")
ROLES = ("planner", "modeler", "solver-advisor", "reviewer", "reporter")


@dataclass(frozen=True)
class ModelSpec:
    id: str
    label: str
    context: int
    tools: bool = True
    json_mode: bool = True
    vision: bool = False
    reasoning: bool = False
    input_usd_per_mtok: float = 0.0
    output_usd_per_mtok: float = 0.0

    def public(self, *, custom: bool = False, fetched: bool = False) -> dict:
        return {
            "id": self.id,
            "label": self.label,
            "context": self.context,
            "tools": self.tools,
            "json_mode": self.json_mode,
            "vision": self.vision,
            "reasoning": self.reasoning,
            "input_usd_per_mtok": self.input_usd_per_mtok,
            "output_usd_per_mtok": self.output_usd_per_mtok,
            "custom": custom,
            "fetched": fetched,
        }


def _m(model_id: str, label: str, context: int, **kwargs) -> ModelSpec:
    return ModelSpec(model_id, label, context, **kwargs)


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    name: str
    name_zh: str
    group: str
    protocol: str
    base_url: str
    auth: str
    models: tuple[ModelSpec, ...]
    monogram: str
    color: str
    notes: str
    notes_zh: str
    key_optional: bool = False
    listable: bool = True
    api_version: str = ""
    region: str = ""
    enabled_by_default: bool = False

    def public_base(self) -> dict:
        supports = {
            "tools": any(item.tools for item in self.models),
            "json_mode": any(item.json_mode for item in self.models),
            "vision": any(item.vision for item in self.models),
            "reasoning": any(item.reasoning for item in self.models),
        }
        return {
            "id": self.id,
            "name": self.name,
            "name_zh": self.name_zh,
            "group": self.group,
            "protocol": self.protocol,
            "auth": self.auth,
            "default_base_url": self.base_url,
            "monogram": self.monogram,
            "color": self.color,
            "notes": self.notes,
            "notes_zh": self.notes_zh,
            "key_optional": self.key_optional,
            "listable": self.listable,
            "builtin": True,
            "api_version": self.api_version,
            "region": self.region,
            "supports": supports,
            "models": [item.public() for item in self.models],
        }


def _p(**kwargs) -> ProviderSpec:
    return ProviderSpec(**kwargs)


PRESETS: tuple[ProviderSpec, ...] = (
    _p(
        id="deepseek",
        name="DeepSeek",
        name_zh="深度求索",
        group="domestic",
        protocol="openai",
        base_url="https://api.deepseek.com/v1",
        auth="bearer",
        monogram="DS",
        color="#4D6BFE",
        notes="OpenAI-compatible chat completions. deepseek-reasoner is the reasoning model.",
        notes_zh="OpenAI 兼容的 Chat Completions。deepseek-reasoner 是推理模型。",
        models=(
            _m("deepseek-chat", "DeepSeek Chat", 131072, input_usd_per_mtok=0.27, output_usd_per_mtok=1.10),
            _m("deepseek-reasoner", "DeepSeek Reasoner", 131072, reasoning=True, json_mode=False, input_usd_per_mtok=0.55, output_usd_per_mtok=2.19),
        ),
    ),
    _p(
        id="qwen",
        name="Alibaba Qwen",
        name_zh="通义千问",
        group="domestic",
        protocol="openai",
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        auth="bearer",
        monogram="QW",
        color="#615CED",
        notes="DashScope / Bailian compatible mode. The key is a DashScope API key.",
        notes_zh="百炼 DashScope 兼容模式。密钥是 DashScope API Key。",
        models=(
            _m("qwen-plus", "Qwen Plus", 131072, input_usd_per_mtok=0.40, output_usd_per_mtok=1.20),
            _m("qwen-turbo", "Qwen Turbo", 1000000, input_usd_per_mtok=0.05, output_usd_per_mtok=0.20),
            _m("qwen-max", "Qwen Max", 32768, input_usd_per_mtok=1.60, output_usd_per_mtok=6.40),
            _m("qwen-vl-max", "Qwen VL Max", 32768, vision=True, input_usd_per_mtok=1.60, output_usd_per_mtok=6.40),
            _m("qwq-32b", "QwQ 32B", 131072, reasoning=True, input_usd_per_mtok=0.20, output_usd_per_mtok=0.60),
        ),
    ),
    _p(
        id="moonshot",
        name="Moonshot Kimi",
        name_zh="月之暗面 Kimi",
        group="domestic",
        protocol="openai",
        base_url="https://api.moonshot.cn/v1",
        auth="bearer",
        monogram="KM",
        color="#5B6CFF",
        notes="Moonshot OpenAI-compatible API. kimi-latest follows the current Kimi model.",
        notes_zh="月之暗面 OpenAI 兼容接口。kimi-latest 指向当前 Kimi 模型。",
        models=(
            _m("kimi-latest", "Kimi", 131072, vision=True, input_usd_per_mtok=0.60, output_usd_per_mtok=2.50),
            _m("moonshot-v1-8k", "Moonshot 8K", 8192, input_usd_per_mtok=0.20, output_usd_per_mtok=2.00),
            _m("moonshot-v1-32k", "Moonshot 32K", 32768, input_usd_per_mtok=0.40, output_usd_per_mtok=3.00),
            _m("moonshot-v1-128k", "Moonshot 128K", 131072, input_usd_per_mtok=0.80, output_usd_per_mtok=4.00),
        ),
    ),
    _p(
        id="zhipu",
        name="Zhipu GLM",
        name_zh="智谱 GLM",
        group="domestic",
        protocol="openai",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        auth="bearer",
        monogram="GL",
        color="#3B5BDB",
        notes="BigModel OpenAI-compatible v4 API.",
        notes_zh="智谱 BigModel OpenAI 兼容 v4 接口。",
        models=(
            _m("glm-4-plus", "GLM-4 Plus", 131072, input_usd_per_mtok=0.70, output_usd_per_mtok=0.70),
            _m("glm-4-air", "GLM-4 Air", 131072, input_usd_per_mtok=0.14, output_usd_per_mtok=0.14),
            _m("glm-4-flash", "GLM-4 Flash", 131072, input_usd_per_mtok=0.01, output_usd_per_mtok=0.01),
            _m("glm-4v-plus", "GLM-4V Plus", 8192, vision=True, input_usd_per_mtok=0.70, output_usd_per_mtok=0.70),
        ),
    ),
    _p(
        id="ernie",
        name="Baidu ERNIE",
        name_zh="百度文心",
        group="domestic",
        protocol="openai",
        base_url="https://qianfan.baidubce.com/v2",
        auth="bearer",
        monogram="BD",
        color="#2932E1",
        notes="Qianfan v2 is OpenAI-compatible. Use a Qianfan API key, not the legacy AK/SK pair.",
        notes_zh="千帆 v2 为 OpenAI 兼容接口。填写千帆 API Key，不是旧版 AK/SK。",
        models=(
            _m("ernie-4.0-turbo-8k", "ERNIE 4.0 Turbo", 8192, input_usd_per_mtok=1.10, output_usd_per_mtok=2.20),
            _m("ernie-4.0-8k-latest", "ERNIE 4.0", 8192, input_usd_per_mtok=1.60, output_usd_per_mtok=4.40),
            _m("ernie-speed-128k", "ERNIE Speed 128K", 131072, input_usd_per_mtok=0.0, output_usd_per_mtok=0.0),
            _m("ernie-3.5-8k", "ERNIE 3.5", 8192, input_usd_per_mtok=0.12, output_usd_per_mtok=0.24),
        ),
    ),
    _p(
        id="doubao",
        name="ByteDance Doubao",
        name_zh="字节豆包",
        group="domestic",
        protocol="openai",
        base_url="https://ark.cn-beijing.volces.com/api/v3",
        auth="bearer",
        monogram="DB",
        color="#3370FF",
        notes="Volcengine Ark. The model field is the endpoint id from the console (ep-…), not the product name.",
        notes_zh="火山方舟。模型栏填写控制台接入点 ID（ep- 开头），不是商品名。",
        models=(
            _m("ep-your-endpoint", "接入点 ep-…", 131072, input_usd_per_mtok=0.11, output_usd_per_mtok=0.28),
        ),
    ),
    _p(
        id="hunyuan",
        name="Tencent Hunyuan",
        name_zh="腾讯混元",
        group="domestic",
        protocol="openai",
        base_url="https://api.hunyuan.cloud.tencent.com/v1",
        auth="bearer",
        monogram="HY",
        color="#0052D9",
        notes="Hunyuan OpenAI-compatible endpoint.",
        notes_zh="混元 OpenAI 兼容接口。",
        models=(
            _m("hunyuan-turbos-latest", "Hunyuan Turbos", 32768, input_usd_per_mtok=0.15, output_usd_per_mtok=0.40),
            _m("hunyuan-lite", "Hunyuan Lite", 256000, input_usd_per_mtok=0.0, output_usd_per_mtok=0.0),
            _m("hunyuan-vision", "Hunyuan Vision", 8192, vision=True, input_usd_per_mtok=1.50, output_usd_per_mtok=4.50),
        ),
    ),
    _p(
        id="minimax",
        name="MiniMax",
        name_zh="MiniMax",
        group="domestic",
        protocol="openai",
        base_url="https://api.minimaxi.com/v1",
        auth="bearer",
        monogram="MM",
        color="#E11D48",
        notes="MiniMax OpenAI-compatible API. The international host is https://api.minimax.io/v1.",
        notes_zh="MiniMax OpenAI 兼容接口。国际站地址是 https://api.minimax.io/v1。",
        models=(
            _m("MiniMax-Text-01", "MiniMax Text 01", 1000000, input_usd_per_mtok=0.20, output_usd_per_mtok=1.10),
            _m("abab6.5s-chat", "ABAB 6.5s", 245760, input_usd_per_mtok=0.20, output_usd_per_mtok=0.20),
        ),
    ),
    _p(
        id="spark",
        name="iFlytek Spark",
        name_zh="讯飞星火",
        group="domestic",
        protocol="openai",
        base_url="https://spark-api-open.xf-yun.com/v1",
        auth="bearer",
        monogram="XF",
        color="#3D7EFF",
        notes="Spark HTTP OpenAI-compatible API. This is not the legacy WebSocket protocol.",
        notes_zh="星火 HTTP OpenAI 兼容接口，不是旧版 WebSocket。",
        models=(
            _m("4.0Ultra", "Spark 4.0 Ultra", 8192, input_usd_per_mtok=0.70, output_usd_per_mtok=0.70),
            _m("generalv3.5", "Spark 3.5", 8192, input_usd_per_mtok=0.30, output_usd_per_mtok=0.30),
            _m("lite", "Spark Lite", 8192, input_usd_per_mtok=0.0, output_usd_per_mtok=0.0),
        ),
    ),
    _p(
        id="stepfun",
        name="StepFun",
        name_zh="阶跃星辰",
        group="domestic",
        protocol="openai",
        base_url="https://api.stepfun.com/v1",
        auth="bearer",
        monogram="ST",
        color="#D97706",
        notes="StepFun OpenAI-compatible API.",
        notes_zh="阶跃星辰 OpenAI 兼容接口。",
        models=(
            _m("step-2-16k", "Step 2 16K", 16384, input_usd_per_mtok=0.50, output_usd_per_mtok=1.40),
            _m("step-1-8k", "Step 1 8K", 8192, input_usd_per_mtok=0.10, output_usd_per_mtok=0.30),
            _m("step-1v-8k", "Step 1V", 8192, vision=True, input_usd_per_mtok=0.20, output_usd_per_mtok=0.60),
        ),
    ),
    _p(
        id="baichuan",
        name="Baichuan",
        name_zh="百川",
        group="domestic",
        protocol="openai",
        base_url="https://api.baichuan-ai.com/v1",
        auth="bearer",
        monogram="BC",
        color="#2563EB",
        notes="Baichuan OpenAI-compatible API.",
        notes_zh="百川 OpenAI 兼容接口。",
        models=(
            _m("Baichuan4", "Baichuan 4", 32768, input_usd_per_mtok=1.40, output_usd_per_mtok=1.40),
            _m("Baichuan3-Turbo", "Baichuan 3 Turbo", 32768, input_usd_per_mtok=0.16, output_usd_per_mtok=0.16),
        ),
    ),
    _p(
        id="yi",
        name="01.AI Yi",
        name_zh="零一万物",
        group="domestic",
        protocol="openai",
        base_url="https://api.lingyiwanwu.com/v1",
        auth="bearer",
        monogram="YI",
        color="#059669",
        notes="01.AI Yi OpenAI-compatible API.",
        notes_zh="零一万物 Yi 的 OpenAI 兼容接口。",
        models=(
            _m("yi-lightning", "Yi Lightning", 16384, input_usd_per_mtok=0.10, output_usd_per_mtok=0.10),
            _m("yi-large", "Yi Large", 32768, input_usd_per_mtok=2.80, output_usd_per_mtok=2.80),
            _m("yi-vision", "Yi Vision", 16384, vision=True, input_usd_per_mtok=0.80, output_usd_per_mtok=0.80),
        ),
    ),
    _p(
        id="sensenova",
        name="SenseTime SenseNova",
        name_zh="商汤日日新",
        group="domestic",
        protocol="openai",
        base_url="https://api.sensenova.cn/compatible-mode/v1",
        auth="bearer",
        monogram="SN",
        color="#7C3AED",
        notes="SenseNova compatible mode.",
        notes_zh="日日新兼容模式。",
        models=(
            _m("SenseChat-5", "SenseChat 5", 131072, input_usd_per_mtok=0.40, output_usd_per_mtok=0.80),
            _m("SenseChat-Turbo", "SenseChat Turbo", 32768, input_usd_per_mtok=0.10, output_usd_per_mtok=0.20),
            _m("SenseChat-Vision", "SenseChat Vision", 8192, vision=True, input_usd_per_mtok=0.40, output_usd_per_mtok=0.80),
        ),
    ),
    _p(
        id="openai",
        name="OpenAI",
        name_zh="OpenAI",
        group="international",
        protocol="openai",
        base_url="https://api.openai.com/v1",
        auth="bearer",
        monogram="OA",
        color="#0F766E",
        notes="Chat Completions by default. Switch the API style to Responses when you want the Responses API.",
        notes_zh="默认使用 Chat Completions。需要 Responses API 时把接口风格改成 Responses。",
        models=(
            _m("gpt-4o", "GPT-4o", 128000, vision=True, input_usd_per_mtok=2.50, output_usd_per_mtok=10.0),
            _m("gpt-4o-mini", "GPT-4o mini", 128000, vision=True, input_usd_per_mtok=0.15, output_usd_per_mtok=0.60),
            _m("gpt-4.1", "GPT-4.1", 1047576, vision=True, input_usd_per_mtok=2.00, output_usd_per_mtok=8.00),
            _m("gpt-4.1-mini", "GPT-4.1 mini", 1047576, vision=True, input_usd_per_mtok=0.40, output_usd_per_mtok=1.60),
            _m("o3-mini", "o3-mini", 200000, reasoning=True, input_usd_per_mtok=1.10, output_usd_per_mtok=4.40),
        ),
    ),
    _p(
        id="anthropic",
        name="Anthropic Claude",
        name_zh="Anthropic Claude",
        group="international",
        protocol="anthropic",
        base_url="https://api.anthropic.com",
        auth="x-api-key",
        monogram="CL",
        color="#C2410C",
        notes="Native Messages API. The key is sent as x-api-key with anthropic-version 2023-06-01.",
        notes_zh="原生 Messages API。密钥放在 x-api-key，版本头为 anthropic-version 2023-06-01。",
        models=(
            _m("claude-sonnet-4-5", "Claude Sonnet 4.5", 200000, vision=True, input_usd_per_mtok=3.0, output_usd_per_mtok=15.0),
            _m("claude-opus-4-1", "Claude Opus 4.1", 200000, vision=True, input_usd_per_mtok=15.0, output_usd_per_mtok=75.0),
            _m("claude-haiku-4-5", "Claude Haiku 4.5", 200000, vision=True, input_usd_per_mtok=1.0, output_usd_per_mtok=5.0),
            _m("claude-3-5-haiku-latest", "Claude 3.5 Haiku", 200000, vision=True, input_usd_per_mtok=0.80, output_usd_per_mtok=4.0),
        ),
    ),
    _p(
        id="gemini",
        name="Google Gemini",
        name_zh="Google Gemini",
        group="international",
        protocol="gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta",
        auth="query",
        monogram="GE",
        color="#1A73E8",
        notes="Native generateContent. The key is sent as the key query parameter and as x-goog-api-key.",
        notes_zh="原生 generateContent。密钥同时放在 key 查询参数和 x-goog-api-key。",
        models=(
            _m("gemini-2.5-pro", "Gemini 2.5 Pro", 1048576, vision=True, reasoning=True, input_usd_per_mtok=1.25, output_usd_per_mtok=10.0),
            _m("gemini-2.5-flash", "Gemini 2.5 Flash", 1048576, vision=True, input_usd_per_mtok=0.15, output_usd_per_mtok=0.60),
            _m("gemini-2.0-flash", "Gemini 2.0 Flash", 1048576, vision=True, input_usd_per_mtok=0.10, output_usd_per_mtok=0.40),
        ),
    ),
    _p(
        id="xai",
        name="xAI Grok",
        name_zh="xAI Grok",
        group="international",
        protocol="openai",
        base_url="https://api.x.ai/v1",
        auth="bearer",
        monogram="XK",
        color="#374151",
        notes="xAI OpenAI-compatible API.",
        notes_zh="xAI 的 OpenAI 兼容接口。",
        models=(
            _m("grok-3", "Grok 3", 131072, input_usd_per_mtok=3.0, output_usd_per_mtok=15.0),
            _m("grok-3-mini", "Grok 3 Mini", 131072, reasoning=True, input_usd_per_mtok=0.30, output_usd_per_mtok=0.50),
            _m("grok-2-vision-1212", "Grok 2 Vision", 32768, vision=True, input_usd_per_mtok=2.0, output_usd_per_mtok=10.0),
        ),
    ),
    _p(
        id="mistral",
        name="Mistral",
        name_zh="Mistral",
        group="international",
        protocol="openai",
        base_url="https://api.mistral.ai/v1",
        auth="bearer",
        monogram="MI",
        color="#F54E00",
        notes="Mistral La Plateforme, OpenAI-compatible.",
        notes_zh="Mistral La Plateforme，OpenAI 兼容。",
        models=(
            _m("mistral-large-latest", "Mistral Large", 131072, input_usd_per_mtok=2.0, output_usd_per_mtok=6.0),
            _m("mistral-small-latest", "Mistral Small", 131072, input_usd_per_mtok=0.10, output_usd_per_mtok=0.30),
            _m("pixtral-large-latest", "Pixtral Large", 131072, vision=True, input_usd_per_mtok=2.0, output_usd_per_mtok=6.0),
            _m("codestral-latest", "Codestral", 32768, input_usd_per_mtok=0.30, output_usd_per_mtok=0.90),
        ),
    ),
    _p(
        id="cohere",
        name="Cohere",
        name_zh="Cohere",
        group="international",
        protocol="openai",
        base_url="https://api.cohere.ai/compatibility/v1",
        auth="bearer",
        monogram="CO",
        color="#39594D",
        notes="Uses Cohere's OpenAI-compatible endpoint so tool calls share one schema. A native v2 adapter is used when the protocol is set to cohere.",
        notes_zh="走 Cohere 的 OpenAI 兼容端点，工具调用与其他兼容接口同一套结构。协议设为 cohere 时改用原生 v2。",
        models=(
            _m("command-a-03-2025", "Command A", 256000, input_usd_per_mtok=2.50, output_usd_per_mtok=10.0),
            _m("command-r-plus", "Command R+", 128000, input_usd_per_mtok=2.50, output_usd_per_mtok=10.0),
            _m("command-r", "Command R", 128000, input_usd_per_mtok=0.15, output_usd_per_mtok=0.60),
        ),
    ),
    _p(
        id="azure",
        name="Azure OpenAI",
        name_zh="Azure OpenAI",
        group="international",
        protocol="openai",
        base_url="https://YOUR_RESOURCE.openai.azure.com",
        auth="azure",
        api_version="2024-10-21",
        monogram="AZ",
        color="#0078D4",
        listable=False,
        notes="The model field is the deployment name. The base URL is https://{resource}.openai.azure.com. The key is sent as the api-key header, and api-version is a query parameter.",
        notes_zh="模型栏填写部署名。地址形如 https://{resource}.openai.azure.com。密钥放在 api-key 头，api-version 放在查询参数。",
        models=(
            _m("gpt-4o", "deployment: gpt-4o", 128000, vision=True, input_usd_per_mtok=2.50, output_usd_per_mtok=10.0),
            _m("gpt-4o-mini", "deployment: gpt-4o-mini", 128000, vision=True, input_usd_per_mtok=0.15, output_usd_per_mtok=0.60),
        ),
    ),
    _p(
        id="bedrock",
        name="AWS Bedrock",
        name_zh="AWS Bedrock",
        group="international",
        protocol="bedrock",
        base_url="https://bedrock-runtime.us-east-1.amazonaws.com",
        auth="aws",
        region="us-east-1",
        monogram="BR",
        color="#C2410C",
        notes="Native Converse API signed with SigV4 (service bedrock). Access key, secret key, optional session token, and region are required. Switch to an OpenAI-compatible gateway (LiteLLM or a Bedrock Access Gateway) if you terminate AWS credentials elsewhere; that path uses a bearer key and the gateway base URL.",
        notes_zh="原生 Converse，使用 SigV4（服务名 bedrock）签名。需要 Access Key、Secret Key、可选的 Session Token 和区域。如果凭证在别处终结，可改成 OpenAI 兼容网关（LiteLLM 或 Bedrock Access Gateway），那时填写网关地址和 Bearer 密钥。",
        models=(
            _m("anthropic.claude-3-5-sonnet-20241022-v2:0", "Claude 3.5 Sonnet", 200000, vision=True, input_usd_per_mtok=3.0, output_usd_per_mtok=15.0),
            _m("anthropic.claude-3-5-haiku-20241022-v1:0", "Claude 3.5 Haiku", 200000, vision=True, input_usd_per_mtok=0.80, output_usd_per_mtok=4.0),
            _m("amazon.nova-pro-v1:0", "Amazon Nova Pro", 300000, vision=True, input_usd_per_mtok=0.80, output_usd_per_mtok=3.20),
            _m("meta.llama3-1-70b-instruct-v1:0", "Llama 3.1 70B", 128000, input_usd_per_mtok=0.72, output_usd_per_mtok=0.72),
        ),
    ),
    _p(
        id="groq",
        name="Groq",
        name_zh="Groq",
        group="international",
        protocol="openai",
        base_url="https://api.groq.com/openai/v1",
        auth="bearer",
        monogram="GQ",
        color="#F55036",
        notes="Groq OpenAI-compatible API.",
        notes_zh="Groq 的 OpenAI 兼容接口。",
        models=(
            _m("llama-3.3-70b-versatile", "Llama 3.3 70B", 131072, input_usd_per_mtok=0.59, output_usd_per_mtok=0.79),
            _m("llama-3.1-8b-instant", "Llama 3.1 8B", 131072, input_usd_per_mtok=0.05, output_usd_per_mtok=0.08),
            _m("mixtral-8x7b-32768", "Mixtral 8x7B", 32768, input_usd_per_mtok=0.24, output_usd_per_mtok=0.24),
        ),
    ),
    _p(
        id="perplexity",
        name="Perplexity",
        name_zh="Perplexity",
        group="international",
        protocol="openai",
        base_url="https://api.perplexity.ai",
        auth="bearer",
        monogram="PX",
        color="#20808D",
        notes="Chat completions live at the host root (/chat/completions), with no /v1 prefix.",
        notes_zh="Chat Completions 在主机根路径 /chat/completions，没有 /v1 前缀。",
        models=(
            _m("sonar", "Sonar", 127072, input_usd_per_mtok=1.0, output_usd_per_mtok=1.0),
            _m("sonar-pro", "Sonar Pro", 200000, input_usd_per_mtok=3.0, output_usd_per_mtok=15.0),
            _m("sonar-reasoning", "Sonar Reasoning", 127072, reasoning=True, input_usd_per_mtok=1.0, output_usd_per_mtok=5.0),
        ),
    ),
    _p(
        id="openrouter",
        name="OpenRouter",
        name_zh="OpenRouter",
        group="aggregator",
        protocol="openai",
        base_url="https://openrouter.ai/api/v1",
        auth="bearer",
        monogram="OR",
        color="#6467F2",
        notes="Routes to many upstreams. Requests send X-Title: Axiom. Prices vary by the upstream model; the figures here are illustrative.",
        notes_zh="转发到多家上游。请求会带上 X-Title: Axiom。价格随上游变化，这里的数字只是示意。",
        models=(
            _m("openai/gpt-4o-mini", "GPT-4o mini", 128000, vision=True, input_usd_per_mtok=0.15, output_usd_per_mtok=0.60),
            _m("anthropic/claude-3.5-sonnet", "Claude 3.5 Sonnet", 200000, vision=True, input_usd_per_mtok=3.0, output_usd_per_mtok=15.0),
            _m("deepseek/deepseek-chat", "DeepSeek Chat", 131072, input_usd_per_mtok=0.27, output_usd_per_mtok=1.10),
            _m("google/gemini-2.0-flash-001", "Gemini 2.0 Flash", 1048576, vision=True, input_usd_per_mtok=0.10, output_usd_per_mtok=0.40),
        ),
    ),
    _p(
        id="siliconflow",
        name="SiliconFlow",
        name_zh="硅基流动",
        group="aggregator",
        protocol="openai",
        base_url="https://api.siliconflow.cn/v1",
        auth="bearer",
        monogram="SF",
        color="#6D28D9",
        notes="SiliconFlow OpenAI-compatible router.",
        notes_zh="硅基流动 OpenAI 兼容路由。",
        models=(
            _m("deepseek-ai/DeepSeek-V3", "DeepSeek V3", 131072, input_usd_per_mtok=0.27, output_usd_per_mtok=1.10),
            _m("Qwen/Qwen2.5-72B-Instruct", "Qwen2.5 72B", 131072, input_usd_per_mtok=0.40, output_usd_per_mtok=0.40),
            _m("THUDM/glm-4-9b-chat", "GLM-4 9B", 131072, input_usd_per_mtok=0.0, output_usd_per_mtok=0.0),
        ),
    ),
    _p(
        id="together",
        name="Together AI",
        name_zh="Together AI",
        group="aggregator",
        protocol="openai",
        base_url="https://api.together.xyz/v1",
        auth="bearer",
        monogram="TG",
        color="#0F766E",
        notes="Together OpenAI-compatible inference.",
        notes_zh="Together 的 OpenAI 兼容推理。",
        models=(
            _m("meta-llama/Llama-3.3-70B-Instruct-Turbo", "Llama 3.3 70B", 131072, input_usd_per_mtok=0.88, output_usd_per_mtok=0.88),
            _m("Qwen/Qwen2.5-7B-Instruct-Turbo", "Qwen2.5 7B", 32768, input_usd_per_mtok=0.30, output_usd_per_mtok=0.30),
            _m("mistralai/Mixtral-8x7B-Instruct-v0.1", "Mixtral 8x7B", 32768, input_usd_per_mtok=0.60, output_usd_per_mtok=0.60),
        ),
    ),
    _p(
        id="fireworks",
        name="Fireworks",
        name_zh="Fireworks",
        group="aggregator",
        protocol="openai",
        base_url="https://api.fireworks.ai/inference/v1",
        auth="bearer",
        monogram="FW",
        color="#EA580C",
        notes="Fireworks inference, OpenAI-compatible.",
        notes_zh="Fireworks 推理，OpenAI 兼容。",
        models=(
            _m("accounts/fireworks/models/llama-v3p3-70b-instruct", "Llama 3.3 70B", 131072, input_usd_per_mtok=0.90, output_usd_per_mtok=0.90),
            _m("accounts/fireworks/models/deepseek-v3", "DeepSeek V3", 131072, input_usd_per_mtok=0.90, output_usd_per_mtok=0.90),
        ),
    ),
    _p(
        id="deepinfra",
        name="DeepInfra",
        name_zh="DeepInfra",
        group="aggregator",
        protocol="openai",
        base_url="https://api.deepinfra.com/v1/openai",
        auth="bearer",
        monogram="DI",
        color="#1D4ED8",
        notes="DeepInfra OpenAI-compatible API.",
        notes_zh="DeepInfra 的 OpenAI 兼容接口。",
        models=(
            _m("meta-llama/Llama-3.3-70B-Instruct", "Llama 3.3 70B", 131072, input_usd_per_mtok=0.23, output_usd_per_mtok=0.40),
            _m("Qwen/Qwen2.5-72B-Instruct", "Qwen2.5 72B", 32768, input_usd_per_mtok=0.35, output_usd_per_mtok=0.40),
        ),
    ),
    _p(
        id="novita",
        name="Novita",
        name_zh="Novita",
        group="aggregator",
        protocol="openai",
        base_url="https://api.novita.ai/v3/openai",
        auth="bearer",
        monogram="NV",
        color="#7C3AED",
        notes="Novita OpenAI-compatible API.",
        notes_zh="Novita 的 OpenAI 兼容接口。",
        models=(
            _m("deepseek/deepseek-v3", "DeepSeek V3", 131072, input_usd_per_mtok=0.40, output_usd_per_mtok=1.30),
            _m("meta-llama/llama-3.3-70b-instruct", "Llama 3.3 70B", 131072, input_usd_per_mtok=0.40, output_usd_per_mtok=0.40),
        ),
    ),
    _p(
        id="ai302",
        name="302.AI",
        name_zh="302.AI",
        group="aggregator",
        protocol="openai",
        base_url="https://api.302.ai/v1",
        auth="bearer",
        monogram="302",
        color="#0284C7",
        notes="302.AI OpenAI-compatible router.",
        notes_zh="302.AI 的 OpenAI 兼容路由。",
        models=(
            _m("gpt-4o-mini", "GPT-4o mini", 128000, vision=True, input_usd_per_mtok=0.15, output_usd_per_mtok=0.60),
            _m("deepseek-chat", "DeepSeek Chat", 131072, input_usd_per_mtok=0.27, output_usd_per_mtok=1.10),
            _m("claude-3-5-sonnet-20241022", "Claude 3.5 Sonnet", 200000, vision=True, input_usd_per_mtok=3.0, output_usd_per_mtok=15.0),
        ),
    ),
    _p(
        id="aihubmix",
        name="AiHubMix",
        name_zh="AiHubMix",
        group="aggregator",
        protocol="openai",
        base_url="https://aihubmix.com/v1",
        auth="bearer",
        monogram="AH",
        color="#4F46E5",
        notes="AiHubMix OpenAI-compatible router.",
        notes_zh="AiHubMix 的 OpenAI 兼容路由。",
        models=(
            _m("gpt-4o-mini", "GPT-4o mini", 128000, vision=True, input_usd_per_mtok=0.15, output_usd_per_mtok=0.60),
            _m("deepseek-chat", "DeepSeek Chat", 131072, input_usd_per_mtok=0.27, output_usd_per_mtok=1.10),
        ),
    ),
    _p(
        id="oneapi",
        name="OneAPI / NewAPI",
        name_zh="OneAPI / NewAPI",
        group="aggregator",
        protocol="openai",
        base_url="http://127.0.0.1:3000/v1",
        auth="bearer",
        key_optional=True,
        monogram="1A",
        color="#059669",
        notes="Self-hosted OneAPI or NewAPI. Point the base URL at your gateway. The token is that gateway's token, not the upstream key.",
        notes_zh="自建 OneAPI 或 NewAPI。把地址改成你的网关。令牌是网关自己的令牌，不是上游密钥。",
        models=(
            _m("gpt-4o-mini", "upstream model id", 128000, tools=True, json_mode=True),
            _m("deepseek-chat", "upstream model id", 131072),
        ),
    ),
    _p(
        id="litellm",
        name="LiteLLM proxy",
        name_zh="LiteLLM 代理",
        group="aggregator",
        protocol="openai",
        base_url="http://127.0.0.1:4000/v1",
        auth="bearer",
        key_optional=True,
        monogram="LT",
        color="#2563EB",
        notes="LiteLLM proxy. The model id is whatever the proxy config exposes. A virtual key is optional on a trusted local port.",
        notes_zh="LiteLLM 代理。模型 ID 以代理配置为准。可信的本机端口可以不填虚拟密钥。",
        models=(
            _m("gpt-4o-mini", "proxy model", 128000),
            _m("claude-3-5-sonnet", "proxy model", 200000, vision=True),
        ),
    ),
    _p(
        id="ollama",
        name="Ollama",
        name_zh="Ollama",
        group="local",
        protocol="openai",
        base_url="http://127.0.0.1:11434/v1",
        auth="bearer",
        key_optional=True,
        monogram="OL",
        color="#44403C",
        notes="Ollama's OpenAI-compatible server. Pull the model in Ollama before testing. No key is required.",
        notes_zh="Ollama 的 OpenAI 兼容服务。测试前先在 Ollama 里拉取模型。不需要密钥。",
        models=(
            _m("llama3.2", "Llama 3.2", 131072, json_mode=True, input_usd_per_mtok=0, output_usd_per_mtok=0),
            _m("qwen2.5", "Qwen 2.5", 32768),
            _m("deepseek-r1", "DeepSeek R1", 131072, reasoning=True, json_mode=False),
        ),
    ),
    _p(
        id="lmstudio",
        name="LM Studio",
        name_zh="LM Studio",
        group="local",
        protocol="openai",
        base_url="http://127.0.0.1:1234/v1",
        auth="bearer",
        key_optional=True,
        monogram="LM",
        color="#0369A1",
        notes="LM Studio local server. Enable the OpenAI-compatible endpoint in the app. Fetch models lists whatever is loaded.",
        notes_zh="LM Studio 本地服务。在应用里打开 OpenAI 兼容端点。获取模型会列出当前已加载的模型。",
        models=(_m("local-model", "loaded model", 32768),),
    ),
    _p(
        id="vllm",
        name="vLLM",
        name_zh="vLLM",
        group="local",
        protocol="openai",
        base_url="http://127.0.0.1:8000/v1",
        auth="bearer",
        key_optional=True,
        monogram="VL",
        color="#15803D",
        notes="vLLM OpenAI-compatible server. The model id is the served model name.",
        notes_zh="vLLM 的 OpenAI 兼容服务。模型 ID 是启动时的服务模型名。",
        models=(_m("served-model", "served model", 32768),),
    ),
    _p(
        id="custom",
        name="OpenAI-compatible",
        name_zh="OpenAI 兼容",
        group="local",
        protocol="openai",
        base_url="http://127.0.0.1:8080/v1",
        auth="bearer",
        key_optional=True,
        monogram="CU",
        color="#57534E",
        notes="Any server that implements /chat/completions. Set the base URL, the key, and the model id. Local hosts may omit the key.",
        notes_zh="任何实现了 /chat/completions 的服务。填写地址、密钥和模型 ID。本机地址可以不填密钥。",
        models=(_m("custom-model", "custom model", 8192),),
    ),
    _p(
        id="mock",
        name="Offline mock",
        name_zh="离线规则",
        group="local",
        protocol="mock",
        base_url="",
        auth="none",
        key_optional=True,
        listable=False,
        enabled_by_default=True,
        monogram="AX",
        color="#78716C",
        notes="Default. No network call. Formulation uses the built-in rules until a role is assigned a provider that has a key.",
        notes_zh="默认。不访问网络。在给角色分配了带密钥的提供方之前，建模使用内置规则。",
        models=(_m("offline", "offline rules", 0, tools=False, json_mode=False, input_usd_per_mtok=0, output_usd_per_mtok=0),),
    ),
)

PRESET_BY_ID: dict[str, ProviderSpec] = {item.id: item for item in PRESETS}

# Legacy settings used this name for the generic compatible endpoint.
LEGACY_PROVIDER_ALIAS = {"openai-compatible": "custom"}


def preset_for(provider_id: str) -> ProviderSpec | None:
    canonical = LEGACY_PROVIDER_ALIAS.get(provider_id, provider_id)
    return PRESET_BY_ID.get(canonical)


def find_model(provider_id: str, model_id: str) -> ModelSpec | None:
    preset = preset_for(provider_id)
    if preset is None:
        return None
    for item in preset.models:
        if item.id == model_id:
            return item
    return None


def required_provider_ids() -> list[str]:
    return [item.id for item in PRESETS]
