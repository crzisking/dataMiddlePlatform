"""LLM 接入层。

通义千问 / DeepSeek 都提供 OpenAI 兼容接口，统一用 openai SDK 调用。
用户在对话中自选模型 —— 这里按「模型名」路由到对应 provider 的 client。
"""

from dataclasses import dataclass
from functools import lru_cache

from langchain_openai import ChatOpenAI
from openai import AsyncOpenAI

from app.core.config import settings


# frozen=True：Provider 是一份不可变的连接信息，避免运行时被误改。
@dataclass(frozen=True)
class Provider:
    name: str  # 仅用于内部标识 / client 复用的 key
    base_url: str  # OpenAI 兼容接口地址（指向通义/DeepSeek，而非 OpenAI 官方）
    api_key: str


_QWEN = Provider("qwen", settings.qwen_base_url, settings.qwen_api_key)
_DEEPSEEK = Provider("deepseek", settings.deepseek_base_url, settings.deepseek_api_key)

# 「模型名 -> 该去哪家」的路由表，同时也是对外暴露的「可选模型白名单」。
# 作用有二：① /meta/models 据此返回前端可选项；② 用户选定后据此路由到对应 provider。
# 一期写死于此（受控白名单，可控成本）；将来要管理页自助增删，把来源换成 DB 即可，接口不变。
MODEL_REGISTRY: dict[str, Provider] = {
    # 通义千问
    "qwen-plus": _QWEN,
    "qwen-max": _QWEN,
    "qwen-turbo": _QWEN,
    # DeepSeek
    "deepseek-chat": _DEEPSEEK,
    "deepseek-reasoner": _DEEPSEEK,
}

DEFAULT_MODEL = settings.qwen_default_model

# 按 provider 复用 client：建连有开销，同一家只建一个，避免每次请求重复创建。
_clients: dict[str, AsyncOpenAI] = {}


def _client_for(provider: Provider) -> AsyncOpenAI:
    if provider.name not in _clients:
        _clients[provider.name] = AsyncOpenAI(
            base_url=provider.base_url,
            # key 为空时填占位串：让对象能正常构造，真正调用才报鉴权错（便于无 key 时先跑通骨架）。
            api_key=provider.api_key or "missing-key",
        )
    return _clients[provider.name]


def get_client(model: str) -> AsyncOpenAI:
    """原生 OpenAI SDK 客户端，供 embedding / 简单一次性调用使用（非 Agent 路径）。

    未知模型回退到默认，避免因前端传错模型名直接抛错。
    """
    provider = MODEL_REGISTRY.get(model)
    if provider is None:
        provider = MODEL_REGISTRY[DEFAULT_MODEL]
    return _client_for(provider)


def available_models() -> list[str]:
    """供 /meta/models 接口返回给前端做模型下拉。"""
    return list(MODEL_REGISTRY.keys())


# lru_cache：同一模型的 ChatModel 只构造一次后复用（构造有开销，且无状态可安全共享）。
@lru_cache(maxsize=16)
def get_chat_model(model: str | None = None, temperature: float = 0.0) -> ChatOpenAI:
    """构造 LangChain ChatOpenAI —— 供 Agent 使用（Agent 框架只接受 LangChain 模型对象）。

    ChatOpenAI 说的是「OpenAI 协议」，靠 base_url 指向通义/DeepSeek 的兼容接口，故能连两家。
    temperature=0：数据中台场景要结果稳定、可复现，默认关掉随机性。
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
    """Embedding 固定走通义（选型已定），与对话模型解耦，单独取 client。"""
    return _client_for(_QWEN)
