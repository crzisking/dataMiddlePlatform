"""大模型接入层：统一管理"调哪家模型、用什么地址和密钥"。

背景：通义千问和 DeepSeek 都提供"OpenAI 兼容接口"——也就是说，用调 OpenAI
的同一套 SDK，只要把请求地址(base_url)换成它们的，就能调它们。所以这里用
一个 openai SDK 就能连两家，靠"模型名"决定这次请求发给谁。
"""

from dataclasses import dataclass
from functools import lru_cache

from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from app.core.config import settings


@dataclass(frozen=True)
class Provider:
    """一家模型厂商的连接信息。frozen=True 表示创建后不可改，避免运行中被误改。"""

    name: str  # 内部标识，也用作复用 client 的 key
    base_url: str  # 接口地址。注意指向的是通义/DeepSeek，不是 OpenAI 官方
    api_key: str


_QWEN = Provider("qwen", settings.qwen_base_url, settings.qwen_api_key)
_DEEPSEEK = Provider("deepseek", settings.deepseek_base_url, settings.deepseek_api_key)

# 模型名 -> 它属于哪家。这张表身兼两职：
#   ① 它就是"可选模型白名单"，/meta/models 接口直接拿它返回给前端做下拉；
#   ② 用户选了某个模型后，靠它查出该把请求发到哪家(地址+密钥)。
# 模型名**不写死在代码里**，而是来自 .env 的 QWEN_MODELS / DEEPSEEK_MODELS（运维从厂商
# 官网/接口查到要用的几个填进去）。为什么不直接拉厂商的 /models 全列出来：通义 /models
# 会返回上百个混杂模型(图像/语音/第三方等)，没法直接做下拉框，必须由运维挑选。
# 加/减模型改 .env 即可，不动代码。


def _build_registry() -> dict[str, Provider]:
    """按 .env 配置的两个模型列表，构建"模型名 → 厂商"的路由表。"""
    registry: dict[str, Provider] = {}
    for name in settings.qwen_model_list:
        registry[name] = _QWEN
    for name in settings.deepseek_model_list:
        registry[name] = _DEEPSEEK
    # 兜底：保证默认模型一定可路由，避免 .env 漏配默认模型导致请求全挂。
    registry.setdefault(settings.qwen_default_model, _QWEN)
    return registry


MODEL_REGISTRY: dict[str, Provider] = _build_registry()

DEFAULT_MODEL = settings.qwen_default_model

# 缓存已建好的 client，每家只建一个。
# 为什么：建 client 要建网络连接，有开销；同一家复用一个就够，不必每次请求新建。
_clients: dict[str, AsyncOpenAI] = {}


def _client_for(provider: Provider) -> AsyncOpenAI:
    if provider.name not in _clients:
        _clients[provider.name] = AsyncOpenAI(
            base_url=provider.base_url,
            # 密钥为空时填个占位串，让 client 能正常建出来；真正发请求时才会因鉴权失败报错。
            # 好处：没填密钥也能先把程序跑起来(骨架阶段方便)。
            api_key=provider.api_key or "missing-key",
        )
    return _clients[provider.name]


def get_client(model: str) -> AsyncOpenAI:
    """拿到原生 openai SDK 客户端，给 embedding / 简单一次性调用用(不走 Agent)。

    传进来的模型名如果不认识，就回退到默认模型，避免前端传错直接报错。
    """
    provider = MODEL_REGISTRY.get(model)
    if provider is None:
        provider = MODEL_REGISTRY[DEFAULT_MODEL]
    return _client_for(provider)


def available_models() -> list[str]:
    """返回所有可选模型名，给 /meta/models 接口用(前端模型下拉框的数据来源)。"""
    return list(MODEL_REGISTRY.keys())


# 把构造好的 ChatOpenAI 缓存起来。
# 为什么：构造它有开销，而同一个模型名构造出来的东西完全一样、又无状态，
# 所以第一次造好就存起来，之后同名直接复用，不重复构造。
@lru_cache(maxsize=16)
def get_chat_model(model: str | None = None, temperature: float = 0.0) -> ChatOpenAI:
    """构造一个 LangChain 风格的聊天模型对象，专门给 Agent 用。

    为什么不用上面的原生 client：Agent 框架(LangGraph)只认 LangChain 的模型对象，
    喂原生 openai client 进去它不认识。
    ChatOpenAI 说的也是"OpenAI 协议"，靠 base_url 指到通义/DeepSeek，所以一样能连两家。
    temperature=0：数据中台要的是稳定、可复现的结果，所以默认把随机性关掉。
    """
    model = model or DEFAULT_MODEL
    provider = MODEL_REGISTRY.get(model) or MODEL_REGISTRY[DEFAULT_MODEL]
    return ChatOpenAI(
        model=model,
        base_url=provider.base_url,
        api_key=provider.api_key or "missing-key",
        temperature=temperature,
    )


def embedding_client() -> AsyncOpenAI:
    """向量化固定走通义(选型已定)，所以单独给一个取通义 client 的函数。"""
    return _client_for(_QWEN)
