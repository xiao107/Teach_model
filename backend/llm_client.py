"""
DeepSeek LLM client: API invocation, streaming consumption, JSON parsing.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)


async def invoke_deepseek(
    api_key: str,
    messages: List[Dict[str, str]],
    model_name: str = "deepseek-chat",
    include_reasoning: bool = False,
    timeout_s: float = 60.0,
) -> str:
    """
    Call the DeepSeek chat completion API and return the assistant reply text.
    """
    if not api_key:
        raise ValueError("Missing DeepSeek API key.")

    url = "https://api.deepseek.com/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"model": model_name, "messages": messages, "stream": True}
    if include_reasoning and "reasoner" in model_name:
        payload["return_reasoning"] = True

    timeout = httpx.Timeout(timeout_s, read=timeout_s, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        logger.info(
            "Calling DeepSeek model=%s messages=%d timeout=%.1fs",
            model_name, len(messages), timeout_s,
        )
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()
            content = await consume_stream_response(response)

    if content:
        return content

    raise RuntimeError("DeepSeek returned an empty response.")


async def stream_deepseek(
    api_key: str,
    messages: List[Dict[str, str]],
    model_name: str = "deepseek-chat",
    timeout_s: float = 60.0,
):
    """Yield content pieces from the DeepSeek streaming API as they arrive."""
    if not api_key:
        raise ValueError("Missing DeepSeek API key.")

    url = "https://api.deepseek.com/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"model": model_name, "messages": messages, "stream": True}

    timeout = httpx.Timeout(timeout_s, read=timeout_s, connect=10.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        logger.info("Streaming DeepSeek model=%s messages=%d", model_name, len(messages))
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()
            async for raw_line in response.aiter_lines():
                if not raw_line:
                    continue
                line = raw_line.strip()
                if line.startswith("data:"):
                    line = line[len("data:"):].strip()
                if line in ("[DONE]", "data: [DONE]"):
                    break
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    logger.debug("Failed to decode stream line: %s", line)
                    continue
                try:
                    choice = data.get("choices", [{}])[0]
                    delta = choice.get("delta", {})
                    piece = delta.get("content") or delta.get("reasoning_content") or ""
                    if piece:
                        yield piece
                except Exception:
                    logger.debug("Unexpected stream payload: %s", data)
                    continue


async def consume_stream_response(response: httpx.Response) -> str:
    """Consume streaming SSE response and concatenate content chunks."""
    chunks: List[str] = []
    async for raw_line in response.aiter_lines():
        if not raw_line:
            continue
        line = raw_line.strip()
        if line.startswith("data:"):
            line = line[len("data:"):].strip()
        if line in ("[DONE]", "data: [DONE]"):
            break
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            logger.debug("Failed to decode stream line: %s", line)
            continue
        try:
            choice = data.get("choices", [{}])[0]
            delta = choice.get("delta", {})
            piece = delta.get("content") or delta.get("reasoning_content") or ""
            if piece:
                chunks.append(piece)
        except Exception:
            logger.debug("Unexpected stream payload: %s", data)
            continue
    return "".join(chunks)


def extract_first_json_object(text: str) -> Optional[str]:
    """
    Scan `text` for the first balanced top-level JSON object (string-aware
    brace matching). Returns the raw JSON substring, or None if not found.
    Handles the common LLM failure mode: prose before/after a bare JSON blob.
    """
    start = text.find("{")
    while start != -1:
        depth = 0
        in_string = False
        escape = False
        for i in range(start, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                continue
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = text[start : i + 1]
                    try:
                        if isinstance(json.loads(candidate), dict):
                            return candidate
                    except (json.JSONDecodeError, ValueError):
                        break  # this { doesn't start a valid object; try next {
        start = text.find("{", start + 1)
    return None


def parse_json_response(response: str) -> Tuple[Optional[Dict[str, Any]], str]:
    """
    Parse JSON from LLM response. Returns (json_data, cleaned_text).
    Handles:
    1. Direct JSON object
    2. JSON in markdown code blocks
    3. Bare JSON object embedded in prose (prose + JSON without fences)
    4. Plain text (returns None, original_text)
    """
    try:
        json_data = json.loads(response.strip())
        if isinstance(json_data, dict):
            return json_data, ""
    except (json.JSONDecodeError, ValueError):
        pass

    json_pattern = r'```(?:json)?\s*(\{[^`]*\})\s*```'
    matches = re.findall(json_pattern, response, re.DOTALL)

    if matches:
        for match in matches:
            try:
                json_data = json.loads(match)
                if isinstance(json_data, dict):
                    cleaned_text = re.sub(json_pattern, "", response, flags=re.DOTALL).strip()
                    return json_data, cleaned_text
            except (json.JSONDecodeError, ValueError):
                continue

    # Case 3: bare JSON object mixed with prose (e.g. LLM writes an intro
    # sentence before the JSON without wrapping it in a code fence).
    raw = extract_first_json_object(response)
    if raw:
        try:
            json_data = json.loads(raw)
            if isinstance(json_data, dict):
                cleaned_text = response.replace(raw, "").strip()
                return json_data, cleaned_text
        except (json.JSONDecodeError, ValueError):
            pass

    return None, response
