"""Provider-agnostic LLM helpers for OpenAI Responses and Anthropic Messages."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
from typing import Any, Callable, Iterable

import anthropic
import requests

from agents.config import build_prompt_cache_key, get_system_prompt_prefix

_OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"


class ProviderFailure(RuntimeError):
    """Normalized provider error with fallback hints."""

    def __init__(self, provider: str, kind: str, message: str, *, retryable: bool = False, fallback_ok: bool = False):
        super().__init__(message)
        self.provider = provider
        self.kind = kind
        self.retryable = retryable
        self.fallback_ok = fallback_ok


@dataclass
class ProviderTrace:
    provider: str
    model: str
    used_fallback: bool = False
    fallback_from: str | None = None


@dataclass
class ProviderResult:
    text: str
    trace: ProviderTrace


ToolDispatcher = Callable[[str, dict[str, Any]], str]


def _hash_for_cache(*parts: str) -> str:
    return build_prompt_cache_key(parts[0], *parts[1:]) if parts else "cache:default"


def _append_system_prefix(system_sections: list[str]) -> list[str]:
    sections = [section for section in system_sections if section]
    prefix = get_system_prompt_prefix()
    if prefix:
        sections.append(prefix)
    return sections


def _note_usage(token_counter: dict[str, Any] | None, usage: dict[str, Any], provider: str) -> None:
    if token_counter is None:
        return
    token_counter["input_tokens"] += int(usage.get("input_tokens") or 0)
    token_counter["output_tokens"] += int(usage.get("output_tokens") or 0)
    token_counter["api_calls"] += 1

    if provider == "openai":
        details = usage.get("input_tokens_details") or {}
        token_counter["cached_input_tokens"] += int(details.get("cached_tokens") or 0)
    else:
        token_counter["cache_creation_input_tokens"] += int(usage.get("cache_creation_input_tokens") or 0)
        token_counter["cache_read_input_tokens"] += int(usage.get("cache_read_input_tokens") or 0)


def _classify_anthropic_error(exc: Exception) -> ProviderFailure:
    if isinstance(exc, anthropic.RateLimitError):
        return ProviderFailure("anthropic", "rate_limit", str(exc), retryable=True, fallback_ok=True)
    message = str(exc)
    low = message.lower()
    if "authentication" in low or "api key" in low or "401" in low:
        return ProviderFailure("anthropic", "auth", message, fallback_ok=True)
    if "model" in low and ("not found" in low or "invalid" in low or "does not exist" in low):
        return ProviderFailure("anthropic", "model", message, fallback_ok=True)
    if "timeout" in low:
        return ProviderFailure("anthropic", "timeout", message, retryable=True, fallback_ok=True)
    return ProviderFailure("anthropic", "transport", message, retryable=True, fallback_ok=True)


def _classify_openai_error(resp: requests.Response | None = None, exc: Exception | None = None) -> ProviderFailure:
    if exc is not None:
        return ProviderFailure("openai", "transport", str(exc), retryable=True, fallback_ok=True)
    assert resp is not None
    message = resp.text
    status = resp.status_code
    if status == 401:
        return ProviderFailure("openai", "auth", message, fallback_ok=True)
    if status == 408:
        return ProviderFailure("openai", "timeout", message, retryable=True, fallback_ok=True)
    if status == 429:
        return ProviderFailure("openai", "rate_limit", message, retryable=True, fallback_ok=True)
    if status >= 500:
        return ProviderFailure("openai", "server", message, retryable=True, fallback_ok=True)
    if status == 400 and "model" in message.lower():
        return ProviderFailure("openai", "model", message, fallback_ok=True)
    return ProviderFailure("openai", "request", message, fallback_ok=False)


def _with_retries(call: Callable[[], Any], provider: str, on_status: Callable[[str], None] | None = None) -> Any:
    last_error: ProviderFailure | None = None
    for attempt in range(5):
        try:
            return call()
        except ProviderFailure as exc:
            last_error = exc
            if not exc.retryable or attempt == 4:
                raise
            wait = min(2 ** (attempt + 1), 30)
            if callable(on_status):
                on_status(f"{provider} rate limited, retrying in {wait}s (attempt {attempt + 1}/5)")
            time.sleep(wait)
    if last_error is not None:
        raise last_error
    raise ProviderFailure(provider, "unknown", f"{provider} call failed", fallback_ok=True)


def _openai_post(payload: dict[str, Any], api_key: str, timeout: int = 120) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(_OPENAI_RESPONSES_URL, headers=headers, json=payload, timeout=timeout)
    except requests.RequestException as exc:
        raise _classify_openai_error(exc=exc) from exc
    if resp.status_code >= 400:
        raise _classify_openai_error(resp=resp)
    return resp.json()


def _extract_openai_text(response: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    texts: list[str] = []
    function_calls: list[dict[str, Any]] = []
    for item in response.get("output", []):
        item_type = item.get("type")
        if item_type in {"function_call", "tool_call"}:
            function_calls.append(item)
            continue
        if item_type != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                texts.append(content["text"])
    if not texts and response.get("output_text"):
        texts.append(response["output_text"])
    return "\n".join(texts).strip(), function_calls


def _build_openai_messages(system_sections: list[str], user_content: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    messages: list[dict[str, Any]] = []
    for section in _append_system_prefix(system_sections):
        messages.append({
            "role": "system",
            "content": [{"type": "input_text", "text": section}],
        })
    if isinstance(user_content, str):
        content = [{"type": "input_text", "text": user_content}]
    else:
        content = []
        for item in user_content:
            if item.get("type") == "text":
                content.append({"type": "input_text", "text": item.get("text", "")})
            elif item.get("type") == "image_base64":
                content.append({
                    "type": "input_image",
                    "image_url": f"data:{item.get('media_type', 'image/png')};base64,{item.get('data', '')}",
                })
            else:
                content.append(item)
    messages.append({"role": "user", "content": content})
    return messages


def _build_anthropic_system(system_sections: list[str]) -> list[dict[str, Any]]:
    return [{"type": "text", "text": section, "cache_control": {"type": "ephemeral"}} for section in _append_system_prefix(system_sections)]


def _build_anthropic_messages(user_content: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(user_content, list):
        content: list[dict[str, Any]] = []
        for item in user_content:
            if item.get("type") == "text":
                content.append({"type": "text", "text": item.get("text", "")})
            elif item.get("type") == "image_base64":
                content.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": item.get("media_type", "image/png"),
                        "data": item.get("data", ""),
                    },
                })
            else:
                content.append(item)
        return [{"role": "user", "content": content}]
    return [{"role": "user", "content": user_content}]


def run_text_completion(
    *,
    primary: Any,
    fallback: Any | None,
    system_sections: list[str],
    user_content: str | list[dict[str, Any]],
    max_output_tokens: int,
    token_counter: dict[str, Any] | None = None,
    on_status: Callable[[str], None] | None = None,
    cache_key_parts: Iterable[str] = (),
) -> ProviderResult:
    """Run a text-only completion with optional provider fallback."""
    try:
        return _run_single_text_completion(
            config=primary,
            system_sections=system_sections,
            user_content=user_content,
            max_output_tokens=max_output_tokens,
            token_counter=token_counter,
            on_status=on_status,
            cache_key_parts=cache_key_parts,
        )
    except ProviderFailure as exc:
        if token_counter is not None and exc.fallback_ok:
            token_counter["fallback_invocations"] += 1
        if not fallback or not exc.fallback_ok:
            raise
        result = _run_single_text_completion(
            config=fallback,
            system_sections=system_sections,
            user_content=user_content,
            max_output_tokens=max_output_tokens,
            token_counter=token_counter,
            on_status=on_status,
            cache_key_parts=cache_key_parts,
        )
        result.trace.used_fallback = True
        result.trace.fallback_from = primary.model
        return result


def _run_single_text_completion(
    *,
    config: Any,
    system_sections: list[str],
    user_content: str | list[dict[str, Any]],
    max_output_tokens: int,
    token_counter: dict[str, Any] | None,
    on_status: Callable[[str], None] | None,
    cache_key_parts: Iterable[str],
) -> ProviderResult:
    if config.provider == "openai":
        api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
        if not api_key:
            raise ProviderFailure("openai", "auth", "OPENAI_API_KEY is not set", fallback_ok=True)
        cache_key = _hash_for_cache(config.cache_key_prefix or "stage", *cache_key_parts)
        payload: dict[str, Any] = {
            "model": config.model,
            "input": _build_openai_messages(system_sections, user_content),
            "max_output_tokens": max_output_tokens,
            "prompt_cache_key": cache_key,
        }
        if config.reasoning_effort:
            payload["reasoning"] = {"effort": config.reasoning_effort}
        if config.cache_retention:
            payload["prompt_cache_retention"] = config.cache_retention

        response = _with_retries(lambda: _openai_post(payload, api_key), "openai", on_status)
        _note_usage(token_counter, response.get("usage") or {}, "openai")
        text, _ = _extract_openai_text(response)
        return ProviderResult(text=text, trace=ProviderTrace(config.provider, config.model))

    client = anthropic.Anthropic()
    kwargs = {
        "model": config.model,
        "max_tokens": max_output_tokens,
        "system": _build_anthropic_system(system_sections),
        "messages": _build_anthropic_messages(user_content),
    }

    def _anthropic_call() -> Any:
        try:
            return client.messages.create(**kwargs)
        except Exception as exc:  # pragma: no cover - normalized below
            raise _classify_anthropic_error(exc) from exc

    response = _with_retries(_anthropic_call, "anthropic", on_status)
    _note_usage(token_counter, {
        "input_tokens": getattr(response.usage, "input_tokens", 0),
        "output_tokens": getattr(response.usage, "output_tokens", 0),
        "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
        "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
    }, "anthropic")
    text = "\n".join(block.text for block in response.content if getattr(block, "type", None) == "text")
    return ProviderResult(text=text.strip(), trace=ProviderTrace(config.provider, config.model))


def run_tool_completion(
    *,
    primary: Any,
    fallback: Any | None,
    system_sections: list[str],
    user_message: str,
    tools: list[dict[str, Any]],
    max_tool_calls: int,
    tool_dispatcher: ToolDispatcher,
    tool_call_counts: dict[str, int] | None = None,
    token_counter: dict[str, Any] | None = None,
    on_status: Callable[[str], None] | None = None,
    cache_key_parts: Iterable[str] = (),
) -> ProviderResult:
    try:
        return _run_single_tool_completion(
            config=primary,
            system_sections=system_sections,
            user_message=user_message,
            tools=tools,
            max_tool_calls=max_tool_calls,
            tool_dispatcher=tool_dispatcher,
            tool_call_counts=tool_call_counts,
            token_counter=token_counter,
            on_status=on_status,
            cache_key_parts=cache_key_parts,
        )
    except ProviderFailure as exc:
        if token_counter is not None and exc.fallback_ok:
            token_counter["fallback_invocations"] += 1
        if not fallback or not exc.fallback_ok:
            raise
        result = _run_single_tool_completion(
            config=fallback,
            system_sections=system_sections,
            user_message=user_message,
            tools=tools,
            max_tool_calls=max_tool_calls,
            tool_dispatcher=tool_dispatcher,
            tool_call_counts=tool_call_counts,
            token_counter=token_counter,
            on_status=on_status,
            cache_key_parts=cache_key_parts,
        )
        result.trace.used_fallback = True
        result.trace.fallback_from = primary.model
        return result


def _openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    mapped = []
    for tool in tools:
        mapped.append({
            "type": "function",
            "name": tool["name"],
            "description": tool.get("description", ""),
            "parameters": tool.get("input_schema", {"type": "object", "properties": {}}),
        })
    return mapped


def _run_single_tool_completion(
    *,
    config: Any,
    system_sections: list[str],
    user_message: str,
    tools: list[dict[str, Any]],
    max_tool_calls: int,
    tool_dispatcher: ToolDispatcher,
    tool_call_counts: dict[str, int] | None,
    token_counter: dict[str, Any] | None,
    on_status: Callable[[str], None] | None,
    cache_key_parts: Iterable[str],
) -> ProviderResult:
    if config.provider == "openai":
        return _run_openai_tool_completion(
            config=config,
            system_sections=system_sections,
            user_message=user_message,
            tools=tools,
            max_tool_calls=max_tool_calls,
            tool_dispatcher=tool_dispatcher,
            tool_call_counts=tool_call_counts,
            token_counter=token_counter,
            on_status=on_status,
            cache_key_parts=cache_key_parts,
        )
    return _run_anthropic_tool_completion(
        config=config,
        system_sections=system_sections,
        user_message=user_message,
        tools=tools,
        max_tool_calls=max_tool_calls,
        tool_dispatcher=tool_dispatcher,
        tool_call_counts=tool_call_counts,
        token_counter=token_counter,
        on_status=on_status,
    )


def _run_openai_tool_completion(
    *,
    config: Any,
    system_sections: list[str],
    user_message: str,
    tools: list[dict[str, Any]],
    max_tool_calls: int,
    tool_dispatcher: ToolDispatcher,
    tool_call_counts: dict[str, int] | None,
    token_counter: dict[str, Any] | None,
    on_status: Callable[[str], None] | None,
    cache_key_parts: Iterable[str],
) -> ProviderResult:
    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise ProviderFailure("openai", "auth", "OPENAI_API_KEY is not set", fallback_ok=True)

    input_payload: list[dict[str, Any]] = _build_openai_messages(system_sections, user_message)
    previous_response_id: str | None = None
    cache_key = _hash_for_cache(config.cache_key_prefix or "coder", *cache_key_parts)
    calls = 0

    while True:
        payload: dict[str, Any] = {
            "model": config.model,
            "input": input_payload,
            "max_output_tokens": 8192,
            "prompt_cache_key": cache_key,
        }
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        if config.reasoning_effort:
            payload["reasoning"] = {"effort": config.reasoning_effort}
        if config.cache_retention:
            payload["prompt_cache_retention"] = config.cache_retention
        if tools and calls < max_tool_calls:
            payload["tools"] = _openai_tools(tools)

        response = _with_retries(lambda: _openai_post(payload, api_key), "openai", on_status)
        _note_usage(token_counter, response.get("usage") or {}, "openai")
        previous_response_id = response.get("id")
        text, function_calls = _extract_openai_text(response)

        if not function_calls or calls >= max_tool_calls:
            return ProviderResult(text=text, trace=ProviderTrace(config.provider, config.model))

        tool_outputs: list[dict[str, Any]] = []
        for call in function_calls:
            calls += 1
            name = call.get("name", "")
            raw_args = call.get("arguments") or "{}"
            try:
                parsed_args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except json.JSONDecodeError:
                parsed_args = {}
            if tool_call_counts is not None:
                tool_call_counts[name] = tool_call_counts.get(name, 0) + 1
            result = tool_dispatcher(name, parsed_args)
            if calls >= max_tool_calls:
                result += (
                    "\n\nCRITICAL SYSTEM WARNING: You have exhausted all tool calls. "
                    "Do NOT call any more functions. You MUST output the complete final code NOW."
                )
            tool_outputs.append({
                "type": "function_call_output",
                "call_id": call.get("call_id") or call.get("id"),
                "output": result,
            })
        input_payload = tool_outputs


def _run_anthropic_tool_completion(
    *,
    config: Any,
    system_sections: list[str],
    user_message: str,
    tools: list[dict[str, Any]],
    max_tool_calls: int,
    tool_dispatcher: ToolDispatcher,
    tool_call_counts: dict[str, int] | None,
    token_counter: dict[str, Any] | None,
    on_status: Callable[[str], None] | None,
) -> ProviderResult:
    client = anthropic.Anthropic()
    messages: list[dict[str, Any]] = [{"role": "user", "content": user_message}]
    calls = 0

    while True:
        kwargs: dict[str, Any] = {
            "model": config.model,
            "max_tokens": 8192,
            "temperature": 0.2,
            "system": _build_anthropic_system(system_sections),
            "messages": messages,
        }
        if tools and calls < max_tool_calls:
            kwargs["tools"] = tools

        def _anthropic_call() -> Any:
            try:
                return client.messages.create(**kwargs)
            except Exception as exc:  # pragma: no cover - normalized below
                raise _classify_anthropic_error(exc) from exc

        response = _with_retries(_anthropic_call, "anthropic", on_status)
        _note_usage(token_counter, {
            "input_tokens": getattr(response.usage, "input_tokens", 0),
            "output_tokens": getattr(response.usage, "output_tokens", 0),
            "cache_creation_input_tokens": getattr(response.usage, "cache_creation_input_tokens", 0) or 0,
            "cache_read_input_tokens": getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        }, "anthropic")

        text_parts: list[str] = []
        tool_use_blocks: list[Any] = []
        for block in response.content:
            if getattr(block, "type", None) == "text":
                text_parts.append(block.text)
            elif getattr(block, "type", None) == "tool_use":
                tool_use_blocks.append(block)

        if response.stop_reason != "tool_use" or not tool_use_blocks or calls >= max_tool_calls:
            return ProviderResult(text="\n".join(text_parts).strip(), trace=ProviderTrace(config.provider, config.model))

        messages.append({"role": "assistant", "content": response.content})
        tool_results = []
        for block in tool_use_blocks:
            calls += 1
            if tool_call_counts is not None:
                tool_call_counts[block.name] = tool_call_counts.get(block.name, 0) + 1
            result = tool_dispatcher(block.name, block.input)
            if calls >= max_tool_calls:
                result += (
                    "\n\nCRITICAL SYSTEM WARNING: You have exhausted all tool calls. "
                    "Do NOT call any more functions. You MUST output the complete final code NOW."
                )
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result,
            })
        messages.append({"role": "user", "content": tool_results})
