"""
Agent orchestration layer (TASK-203: multi-step action loop).

Flow:
  user command -> LLM (JSON: reply + action | actions[]) -> execute actions
  -> results fed back -> LLM decides to continue or finish (max N steps).

Backward-compatible exports: `_parse_json_response`, `ConversationManager`.
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend import actions, data_loader
from backend.config import settings
from backend.llm_client import invoke_deepseek, parse_json_response as _parse_json_response
from backend.prompts import STUDENT_SYSTEM_PROMPT, get_level_description as _get_default_level_description
from backend.state import ConversationManager

logger = logging.getLogger(__name__)

# Async callback receiving (event_type, text) pieces for SSE forwarding.
DeltaCallback = Callable[[str, str], Awaitable[None]]


def _build_context_string(manager: ConversationManager) -> str:
    data, name = manager.get_data()
    parts: List[str] = ["\n【当前会话上下文】"]
    if data is not None:
        parts.append(
            f"- 已加载数据集：{name}（{data.shape[0]} 行 × {data.shape[1]} 列）"
        )
    else:
        parts.append("- 尚未加载数据集")
    if manager.current_model is not None:
        parts.append(f"- 当前模型：{manager.current_model_name}（{manager.current_task_type}）")
    if manager.metric_history:
        parts.append(f"- 已训练过的模型：{', '.join(manager.metric_history.keys())}")
    return "\n".join(parts)


def _build_messages(manager: ConversationManager, command: str, level_prompt: Optional[str], student_level: str) -> List[Dict[str, str]]:
    system_message = (
        f"{STUDENT_SYSTEM_PROMPT}\n\n"
        f"{_build_context_string(manager)}"
        f"\n\n【你的当前水平】：{level_prompt or _get_default_level_description(student_level)}"
    )
    messages = [{"role": "system", "content": system_message}]
    history = manager.get_history()
    if len(history) > 1:
        messages.extend(history[:-1])
    messages.append({"role": "user", "content": command})
    return messages


def _extract_actions(json_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Normalize supported shapes into a list of action dicts:
      - {"actions": [{"action": "...", "params": {...}}, ...]}
      - {"actions": ["split", "train"]}            (bare name strings)
      - {"action": "...", "params": {...}}
    """
    result: List[Dict[str, Any]] = []

    def _normalize(item: Any) -> Optional[Dict[str, Any]]:
        if isinstance(item, str) and item.strip():
            return {"action": item.strip(), "params": {}}
        if isinstance(item, dict):
            name = item.get("action") or item.get("name") or item.get("type")
            if name:
                return {"action": str(name), "params": item.get("params") or {}}
        return None

    raw_actions = json_data.get("actions")
    if isinstance(raw_actions, list):
        for item in raw_actions[: settings.agent_max_steps]:
            normalized = _normalize(item)
            if normalized:
                result.append(normalized)
    else:
        normalized = _normalize(json_data)
        if normalized:
            result.append(normalized)
    return result


async def process_user_command(
    command: str,
    manager: ConversationManager,
    api_key: str,
    model_name: str = "",
    student_level: str = "intermediate",
    level_prompt: Optional[str] = None,
    on_delta: Optional[DeltaCallback] = None,
) -> Dict[str, Any]:
    """
    Process a user command with a multi-step agent loop.

    Returns {"reply": str, "chart": Optional[dict], "steps": [action names]}.
    `on_delta(event, text)` receives streaming pieces:
      event="delta"  -> raw LLM text piece (streaming preview)
      event="status" -> action execution progress
    """
    model_name = model_name or settings.deepseek_model
    logger.info("Processing command: %s", command)
    manager.add_message("user", command)
    messages = _build_messages(manager, command, level_prompt, student_level)

    final_reply = ""
    chart_payload: Optional[Dict[str, Any]] = None
    executed_steps: List[str] = []
    executed_signatures: set = set()  # (action, params) dedup guard within one command

    try:
        for step in range(settings.agent_max_steps):
            # ---- LLM round (streamed) ----
            if on_delta is not None:
                chunks: List[str] = []
                async for piece in _stream_round(api_key, messages, model_name):
                    chunks.append(piece)
                    await on_delta("delta", piece)
                response = "".join(chunks)
            else:
                response = await invoke_deepseek(api_key, messages, model_name=model_name)

            json_data, cleaned = _parse_json_response(response)
            if json_data is None:
                logger.warning(
                    "LLM round %d returned no parseable JSON (len=%d), treating as plain reply",
                    step + 1, len(response),
                )
                final_reply = response.strip()
                break

            round_reply = str(json_data.get("reply", "") or cleaned or "").strip()
            action_list = _extract_actions(json_data)

            if not action_list:
                final_reply = round_reply
                break

            # ---- execute this group of actions ----
            executed: List[Dict[str, str]] = []
            for act in action_list:
                signature = (
                    act["action"],
                    json.dumps(act.get("params") or {}, sort_keys=True, ensure_ascii=False),
                )
                if signature in executed_signatures:
                    logger.info("Skipping duplicate action %s (already executed)", act["action"])
                    executed.append(
                        {"action": act["action"], "result": "（该动作在本次指令中已执行过，已自动跳过，结果见上文）"}
                    )
                    continue
                executed_signatures.add(signature)
                executed_steps.append(act["action"])
                if on_delta is not None:
                    await on_delta("status", f"执行 {act['action']}")
                appendix, chart = await asyncio.to_thread(
                    actions.execute_action, act["action"], act["params"], manager
                )
                if chart is not None:
                    chart_payload = chart
                executed.append({"action": act["action"], "result": appendix.strip()})

            # Feed results back for the next round
            feedback = (
                "【系统执行结果】\n"
                + "\n\n".join(
                    f"### {e['action']}\n{e['result'] or '（图表已生成）'}" for e in executed
                )
                + "\n\n以上动作已实际执行完毕，结果真实有效。请根据以上结果继续："
                "若任务未完成，只输出**尚缺少的**下一组 actions（严禁重复执行上面已经"
                "执行过并回填了结果的动作）；若已完成，输出总结性 reply（不要带 action）。"
            )
            messages = messages + [
                {"role": "assistant", "content": json.dumps(json_data, ensure_ascii=False)},
                {"role": "user", "content": feedback},
            ]
            if round_reply:
                final_reply = round_reply

        if not final_reply:
            final_reply = "老师，这一轮的操作已经完成。"

        manager.add_message("assistant", final_reply)
        result: Dict[str, Any] = {"reply": final_reply, "steps": executed_steps}
        if chart_payload:
            result["chart"] = chart_payload
        return result

    except Exception as exc:
        error_msg = f"抱歉老师，处理您的指令时出错了：{exc}\n您能再解释一下吗？"
        manager.add_message("assistant", error_msg)
        logger.exception("Error while processing command")
        return {"reply": error_msg, "steps": executed_steps}


async def _stream_round(api_key: str, messages: List[Dict[str, str]], model_name: str):
    """Yield pieces of one streamed LLM round."""
    from backend.llm_client import stream_deepseek

    async for piece in stream_deepseek(
        api_key, messages, model_name=model_name, timeout_s=settings.llm_timeout_s
    ):
        yield piece


async def generate_session_title(
    first_command: str,
    first_reply: str,
    api_key: str,
    model_name: str = "",
) -> str:
    """
    TASK-201: generate a short session title (<= 20 chars) via LLM.
    Falls back to a truncated command on any failure.
    """
    model_name = model_name or settings.deepseek_model
    try:
        prompt = (
            "根据下面的对话开头，生成一个不超过20字的简短会话标题，"
            "直接返回标题文本，不要引号、不要句号、不要解释。\n\n"
            f"老师：{first_command[:200]}\n"
            f"学生：{first_reply[:200]}"
        )
        response = await invoke_deepseek(
            api_key,
            [{"role": "user", "content": prompt}],
            model_name=model_name,
        )
        title = response.strip().strip("\"'「」『』").splitlines()[0][:20]
        if title:
            return title
    except Exception:
        logger.exception("Title generation failed, using fallback")
    return first_command[:20]
