import asyncio
import json
import os

import httpx

LLM_TIMEOUT_SECONDS = 90

SYSTEM_PROMPT = """你是一个商业情报分析员。不要写空话。请基于给定资讯判断：
1. 这件事是什么
2. 为什么现在发生
3. 是否只是噪音
4. 可能影响哪些行业或公司
5. 是否存在可验证的商业机会
6. 下一步应该调查什么
请用中文输出，结构清晰，避免夸张判断。"""


class LLMConfigError(Exception):
    pass


class LLMCallError(Exception):
    def __init__(self, detail: str | dict):
        self.detail = detail
        if isinstance(detail, dict):
            super().__init__(str(detail.get("message") or "LLM upstream error"))
        else:
            super().__init__(str(detail))


def daily_limit() -> int:
    raw = os.getenv("LLM_DAILY_LIMIT", "20").strip() or "20"
    try:
        return int(raw)
    except ValueError:
        return 20


def build_chat_completions_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


def require_config() -> tuple[str, str, str]:
    base = os.getenv("LLM_BASE_URL", "").strip()
    key = os.getenv("LLM_API_KEY", "").strip()
    model = os.getenv("LLM_MODEL_FAST", "").strip()
    if not key:
        raise LLMConfigError("未配置 LLM_API_KEY，请先在 .env 填写模型密钥")
    if not base:
        raise LLMConfigError("未配置 LLM_BASE_URL，请先在 .env 填写模型网关地址")
    if not model:
        raise LLMConfigError("未配置 LLM_MODEL_FAST，请先填写模型名称")
    return base, key, model


def _redact(text: str, secret: str) -> str:
    if secret and secret in text:
        return text.replace(secret, "[redacted]")
    return text


def _upstream_body(response: httpx.Response, secret: str):
    raw = _redact(response.text or "", secret)
    if len(raw) > 8000:
        raw = raw[:8000]
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def _upstream_error(
    status_code: int | None,
    model: str,
    url: str,
    upstream_response,
    message: str,
    secret: str = "",
) -> dict:
    safe_response = upstream_response
    if isinstance(upstream_response, str):
        safe_response = _redact(upstream_response, secret)
    return {
        "message": message,
        "status_code": status_code,
        "model": model,
        "url": _redact(url, secret),
        "upstream_response": safe_response,
    }


def _temperature_rejected(response: httpx.Response) -> bool:
    if response.status_code != 400:
        return False
    text = (response.text or "").lower()
    if "temperature" not in text:
        return False
    return "unsupported" in text or "not supported" in text or "not support" in text


def _timeout_error(model: str, url: str, secret: str) -> dict:
    return {
        "message": "模型接口超时，请检查上游服务或网络",
        "model": model,
        "url": _redact(url, secret),
        "timeout_seconds": LLM_TIMEOUT_SECONDS,
    }


async def _post(
    client: httpx.AsyncClient,
    endpoint: str,
    payload: dict,
    headers: dict,
    model: str,
    secret: str,
) -> httpx.Response:
    try:
        return await asyncio.wait_for(
            client.post(endpoint, json=payload, headers=headers),
            timeout=LLM_TIMEOUT_SECONDS,
        )
    except (httpx.TimeoutException, asyncio.TimeoutError) as exc:
        raise LLMCallError(_timeout_error(model, endpoint, secret)) from exc
    except httpx.HTTPError as exc:
        raise LLMCallError(
            _upstream_error(
                None,
                model,
                endpoint,
                exc.__class__.__name__,
                f"模型接口请求失败: {exc.__class__.__name__}",
                secret,
            )
        ) from exc


async def analyze(title: str, source: str, url: str, summary: str) -> tuple[str, str]:
    base, key, model = require_config()
    endpoint = build_chat_completions_url(base)
    user_prompt = f"title: {title}\nsource: {source}\nurl: {url}\nsummary: {summary or ''}"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.2,
    }
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=LLM_TIMEOUT_SECONDS) as client:
        response = await _post(client, endpoint, payload, headers, model, key)
        if _temperature_rejected(response):
            payload.pop("temperature", None)
            response = await _post(client, endpoint, payload, headers, model, key)

    if response.status_code >= 400:
        raise LLMCallError(
            _upstream_error(
                response.status_code,
                model,
                endpoint,
                _upstream_body(response, key),
                "LLM upstream error",
                key,
            )
        )

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LLMCallError(
            _upstream_error(
                response.status_code,
                model,
                endpoint,
                _upstream_body(response, key),
                "模型接口返回格式异常",
                key,
            )
        ) from exc

    text = str(content or "").strip()
    if not text:
        raise LLMCallError(
            _upstream_error(
                response.status_code,
                model,
                endpoint,
                _upstream_body(response, key),
                "模型接口返回空内容",
                key,
            )
        )
    return model, text
