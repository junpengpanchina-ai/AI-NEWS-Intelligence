import os

import httpx

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
    pass


def daily_limit() -> int:
    raw = os.getenv("LLM_DAILY_LIMIT", "20").strip() or "20"
    try:
        return int(raw)
    except ValueError:
        return 20


def build_chat_completions_url(base_url: str) -> str:
    base = (base_url or "").strip().rstrip("/")
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


async def analyze(title: str, source: str, url: str, summary: str) -> tuple[str, str]:
    base, key, model = require_config()
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
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                build_chat_completions_url(base),
                json=payload,
                headers=headers,
            )
    except httpx.TimeoutException as exc:
        raise LLMCallError("模型接口超时，请检查上游服务或网络") from exc
    except httpx.HTTPError as exc:
        raise LLMCallError(f"模型接口请求失败: {exc.__class__.__name__}") from exc

    if response.status_code in (401, 403):
        raise LLMCallError("模型接口鉴权失败，请检查 API Key")
    if response.status_code >= 400:
        raise LLMCallError(f"模型接口返回 {response.status_code}")

    try:
        data = response.json()
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise LLMCallError("模型接口返回格式异常") from exc

    text = str(content or "").strip()
    if not text:
        raise LLMCallError("模型接口返回空内容")
    return model, text
