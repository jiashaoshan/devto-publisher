#!/usr/bin/env python3
"""
dev.to LLM 调用模块 — 使用 openclaw 配置的 baiduqianfancodingplan 模型
从 ~/.openclaw/openclaw.json 读取 provider 配置
"""
import json
import logging
import os
import re
import requests
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

OPENCLAW_CONFIG_PATH = os.path.expanduser("~/.openclaw/openclaw.json")
DEFAULT_TIMEOUT = 120
DEFAULT_MODEL = "qianfan-code-latest"


def _load_openclaw_config() -> dict:
    """加载 openclaw 配置"""
    try:
        if os.path.exists(OPENCLAW_CONFIG_PATH):
            with open(OPENCLAW_CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"无法加载 openclaw 配置: {e}")
    return {}


def get_provider_config() -> dict:
    """获取 baiduqianfancodingplan provider 配置"""
    config = _load_openclaw_config()
    providers = config.get("models", {}).get("providers", {})
    provider = providers.get("baiduqianfancodingplan", {})

    if not provider:
        logger.warning("openclaw.json 中未找到 baiduqianfancodingplan provider")
        # 降级：从 env 读取
        env = config.get("env", {})
        api_key = env.get("BAIDU_API_KEY", os.environ.get("BAIDU_API_KEY", ""))
        if api_key:
            provider = {
                "baseUrl": "https://qianfan.baidubce.com/v2/coding",
                "apiKey": api_key,
                "api": "openai-completions",
                "models": [{"id": "qianfan-code-latest"}]
            }
    return provider


def get_api_key() -> str:
    """获取 API Key"""
    provider = get_provider_config()
    key = provider.get("apiKey", "")
    if not key:
        # 从环境变量尝试
        key = os.environ.get("BAIDU_API_KEY", "")
        if not key:
            config = _load_openclaw_config()
            env = config.get("env", {})
            key = env.get("BAIDU_API_KEY", "")
    return key


def get_base_url() -> str:
    """获取 API Base URL"""
    provider = get_provider_config()
    url = provider.get("baseUrl", "")
    if not url:
        url = "https://qianfan.baidubce.com/v2/coding"
    return url


def get_model() -> str:
    """获取模型名称"""
    provider = get_provider_config()
    models = provider.get("models", [])
    if models:
        return models[0].get("id", DEFAULT_MODEL)
    return DEFAULT_MODEL


def call_llm(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """
    调用百度千帆 Coding Plan API

    Args:
        system_prompt: 系统提示词
        user_prompt: 用户提示词
        model: 模型名称，默认 qianfan-code-latest
        temperature: 温度参数
        max_tokens: 最大生成 token 数
        timeout: 超时时间（秒）

    Returns:
        str: LLM 返回的文本内容
    """
    api_key = get_api_key()
    base_url = get_base_url()
    model_name = model or get_model()

    if not api_key:
        raise ValueError("BAIDU_API_KEY 未找到，请检查 openclaw.json 配置")

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]

    payload = {
        "model": model_name,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    logger.debug(f"LLM 请求: model={model_name}, system={len(system_prompt)}ch, user={len(user_prompt)}ch")

    import time as _time
    # 请求前等待 1s 降低限流概率
    _time.sleep(1)
    max_retries = 3
    for attempt in range(max_retries):
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )

            if resp.status_code == 429:
                wait = (attempt + 1) * 5
                logger.warning(f"429 限流，等待 {wait}s 后重试 (attempt {attempt+1}/{max_retries})")
                _time.sleep(wait)
                continue

            resp.raise_for_status()

            data = resp.json()
            content = data["choices"][0]["message"]["content"].strip()
            logger.debug(f"LLM 响应: {len(content)} 字符")
            return content

        except requests.exceptions.Timeout:
            logger.error(f"LLM 请求超时 (>{timeout}s)")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"LLM 请求失败: {e}")
            if hasattr(e, "response") and e.response is not None:
                try:
                    err_detail = e.response.json()
                    if "rate" in str(err_detail).lower() or "limit" in str(err_detail).lower() or "quota" in str(err_detail).lower():
                        wait = (attempt + 1) * 10
                        logger.warning(f"限流/配额不足，等待 {wait}s 后重试")
                        _time.sleep(wait)
                        continue
                    logger.error(f"API 错误详情: {json.dumps(err_detail, ensure_ascii=False)}")
                except Exception:
                    logger.error(f"API 原始响应: {e.response.text[:500]}")
            raise
        except (KeyError, IndexError, json.JSONDecodeError) as e:
            logger.error(f"解析 LLM 响应失败: {e}")
            raise ValueError(f"LLM 返回格式异常: {e}")
    else:
        raise RuntimeError(f"LLM 请求失败: 超过最大重试次数 ({max_retries})")


def call_llm_json(
    system_prompt: str,
    user_prompt: str,
    model: Optional[str] = None,
    temperature: float = 0.7,
    max_tokens: int = 4096,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """
    调用 LLM 并解析 JSON 响应
    不使用 response_format 约束（避免截断输出），提示词已要求 JSON 格式

    Returns:
        dict: 解析后的 JSON 对象
    """
    content = call_llm(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
    )

    # 尝试解析 JSON
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 尝试从文本中提取 JSON 对象
    json_match = re.search(r'\{.*\}', content, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # 尝试提取 JSON 数组
    json_match = re.search(r'\[.*\]', content, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    logger.error(f"LLM 返回不是有效 JSON: {content[:300]}")
    return {}
