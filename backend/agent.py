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
import re
from typing import Any, Awaitable, Callable, Dict, List, Optional

from backend import actions, data_loader
from backend.config import settings
from backend.llm_client import invoke_deepseek, parse_json_response as _parse_json_response
from backend.prompts import STUDENT_SYSTEM_PROMPT, get_level_description as _get_default_level_description
from backend.state import ConversationManager

logger = logging.getLogger(__name__)

# Async callback receiving (event_type, text) pieces for SSE forwarding.
DeltaCallback = Callable[[str, str], Awaitable[None]]

# Human-readable labels for action names, used by the frontend result cards.
ACTION_LABELS: Dict[str, str] = {
    "load": "数据集加载",
    "preview": "数据预览",
    "check_missing": "缺失值检查",
    "fill_missing": "缺失值填充",
    "encode": "特征编码",
    "split": "数据分割",
    "train": "模型训练",
    "evaluate": "模型评估",
    "plot": "图表生成",
    "knn_train": "模型训练",
    "svm_train": "模型训练",
    "gbt_train": "模型训练",
}

# Heuristic: does the user command look like it asks for an operation?
# Used to decide whether a no-action reply deserves a corrective retry.
_OPERATION_KEYWORD_RE = re.compile(
    r"加载|预览|查看|检查|填充|编码|分割|划分|训练|评估|预测|画|绘制|图表|热力|直方|散点|箱线|折线|柱状|"
    r"plot|load|preview|missing|fill|encode|split|train|evaluat|knn|svm|gbt|forest|regression|tree|chart",
    re.IGNORECASE,
)

_CORRECTIVE_NUDGE = (
    "【系统纠偏】你上一次的回复只有过渡性文字，没有包含任何 action 或 actions 字段，"
    "系统什么都没有执行，这是严重错误。请立刻重新输出完整 JSON："
    "根据老师的指令给出 action（单步）或 actions 数组（多步，最多 5 步），"
    "reply 保持简短。不要输出任何不含动作的过渡语。"
)


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

    Returns {"reply": str, "chart": Optional[dict], "steps": [action names],
             "results": [{action, title, text, chart}, ...]}.
    `on_delta(event, text)` receives streaming pieces:
      event="delta"  -> raw LLM text piece (streaming preview)
      event="status" -> action execution progress
      event="result" -> JSON-encoded result entry (table/chart card data)
    """
    model_name = model_name or settings.deepseek_model
    logger.info("Processing command: %s", command)
    manager.add_message("user", command)
    messages = _build_messages(manager, command, level_prompt, student_level)

    final_reply = ""
    chart_payload: Optional[Dict[str, Any]] = None
    results: List[Dict[str, Any]] = []
    executed_steps: List[str] = []
    executed_signatures: set = set()  # (action, params) dedup guard within one command
    corrective_used = False  # transition-only corrective retry, at most once

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
            action_list = _extract_actions(json_data) if json_data else []

            if not action_list:
                round_reply = (
                    str(json_data.get("reply", "") or "").strip()
                    if json_data else ""
                ) or (cleaned or response).strip()

                # P0-2: transition-only guard — the model produced prose like
                # "好的老师，正在训练模型：" without any action. Nudge once.
                if (
                    step == 0
                    and not corrective_used
                    and _OPERATION_KEYWORD_RE.search(command)
                ):
                    corrective_used = True
                    logger.warning(
                        "Round 1 returned no actions (transition-only?), nudging model. reply=%r",
                        round_reply[:80],
                    )
                    if on_delta is not None:
                        await on_delta("status", "重新组织回复...")
                    messages = messages + [
                        {"role": "assistant", "content": response},
                        {"role": "user", "content": _CORRECTIVE_NUDGE},
                    ]
                    continue

                final_reply = round_reply
                break

            round_reply = str(json_data.get("reply", "") or cleaned or "").strip()

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

                appendix_text = appendix.strip()
                # Failed actions (❌) must NOT count as "already executed":
                # e.g. train-before-load failed, and after load the model must
                # be allowed to retry the same train. Only success is sticky.
                if "❌" in appendix_text:
                    executed_signatures.discard(signature)
                    logger.info("Action %s failed, allowed to retry later", act["action"])
                entry: Dict[str, Any] = {
                    "action": act["action"],
                    "title": ACTION_LABELS.get(act["action"], act["action"]),
                    "text": appendix_text,
                    "chart": chart,
                }
                results.append(entry)
                executed.append({"action": act["action"], "result": appendix.strip()})

                # P0-3: push each result to the frontend immediately so tables
                # and charts render live, instead of a single overwritten slot.
                if on_delta is not None:
                    await on_delta("result", json.dumps(entry, ensure_ascii=False))

            # Feed results back for the next round
            feedback = (
                "【系统执行结果】\n"
                + "\n\n".join(
                    f"### {e['action']}\n{e['result'] or '（图表已生成）'}" for e in executed
                )
                + "\n\n以上动作已实际执行完毕，结果真实有效。请根据以上结果继续：\n"
                "- 若某动作的结果是 ❌ 失败，请先补齐它缺失的前置条件（例如先 load 数据集），"
                "然后**重新输出该失败的动作**——失败的动作允许且应当重试；\n"
                "- 若任务未完成，只输出**尚缺少的**下一组 actions（严禁重复执行上面已经"
                "成功执行过并回填了结果的动作）；\n"
                "- 若已完成，输出总结性 reply（不要带 action）。"
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
        result: Dict[str, Any] = {
            "reply": final_reply,
            "steps": executed_steps,
            "results": results,
        }
        if chart_payload:
            result["chart"] = chart_payload  # legacy single-slot, kept for compat
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
