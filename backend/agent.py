"""
Core agent logic for handling user commands and managing conversation state.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pandas as pd
from sklearn.preprocessing import StandardScaler

from . import data_loader


SYSTEM_PROMPT = """你是一个专业、耐心且友好的“数据科学助手”。

你的核心职能是：
1. 引导用户：主动引导用户完成数据处理任务，而不是被动等待命令。
2. 加载数据：帮助用户从预设的数据集列表中（Iris, Wine, Breast Cancer, California Housing, 以及 'dot' 数据集）选择并加载数据。
3. 数据交互：基于加载的数据，回答用户的问题，如“显示数据前5行”、“数据有哪些列”、“这个数据集是用于分类还是回归？”。
4. 保持上下文：你必须记住当前会话中已经加载了哪个数据集，后续所有操作都围绕该数据集展开，除非用户明确要求更换。
5. 友好交流：你的回复应该像对话一样，清晰、简洁，并在适当的时候使用 Markdown 格式化（例如代码块、列表）。
6. 引导式流程：按步骤引导用户完成数据集选择、数据清洗、EDA、算法推荐、模型训练评估，再到总结报告，每一步都提供选项并等待用户选择。

你的工作流程严格遵循以下模板：
* 开场：当用户开始对话时，你必须首先问候用户，并询问他们想加载哪个数据集。
* 数据加载后：当一个数据集被加载后，你必须确认加载成功，并询问用户“接下来想做什么？”（例如：查看数据、数据摘要、预处理等）。
* 切换数据：如果用户想要加载新数据，你要确认并清空当前状态，再加载新的。
"""

DATASET_CATALOG = (
    "可选数据集列表：\n"
    "1) Iris（鸢尾花）：150 样本，4 个特征，三分类，入门分类示例。\n"
    "2) Wine（葡萄酒）：178 样本，13 理化特征，多分类，质量辨别。\n"
    "3) Breast Cancer（乳腺癌）：569 样本，30 特征，二分类，良/恶性判别。\n"
    "4) California Housing（加州房价）：20,640 样本，8 特征，回归预测房价中位数。\n"
    "5) dot 图数据：自备 data.dot，解析为边列表。\n"
    "回复示例：“加载 Iris 数据集”或“选择 California Housing”。"
)


class ConversationManager:
    """
    Stores dialogue history and the currently loaded dataset.
    """

    def __init__(self) -> None:
        self.history: List[Dict[str, str]] = []
        self.current_data: Optional[pd.DataFrame] = None
        self.current_dataset_name: Optional[str] = None

    def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})

    def get_history(self) -> List[Dict[str, str]]:
        return list(self.history)

    def set_data(self, df: pd.DataFrame, name: str) -> None:
        self.current_data = df
        self.current_dataset_name = name

    def get_data(self) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        return self.current_data, self.current_dataset_name

    def clear_context(self) -> None:
        self.history.clear()
        self.current_data = None
        self.current_dataset_name = None


async def invoke_deepseek(
    api_key: str,
    messages: List[Dict[str, str]],
    model_name: str = "deepseek-chat",
    include_reasoning: bool = True,
) -> str:
    """
    Call the DeepSeek chat completion API and return the assistant reply text.
    """
    if not api_key:
        raise ValueError("Missing DeepSeek API key.")

    url = "https://api.deepseek.com/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}"}
    payload = {"model": model_name, "messages": messages}
    if include_reasoning and "reasoner" in model_name:
        payload["return_reasoning"] = True

    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

    try:
        message = data["choices"][0]["message"]
        content = message.get("content", "")
        reasoning = (
            message.get("reasoning_content")
            or message.get("model_extra", {}).get("reasoning_content")
        )
        if include_reasoning and reasoning:
            return f"**思考过程**\n{reasoning}\n\n**最终回答**\n{content}"
        return content
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Unexpected DeepSeek response: {data}") from exc


def _detect_dataset_name(command_lower: str) -> Optional[str]:
    keywords = {
        "iris": ["iris", "鸢尾"],
        "wine": ["wine", "葡萄酒"],
        "breast_cancer": ["breast", "cancer", "乳腺", "癌"],
        "california_housing": ["california", "housing", "房价", "加州"],
        "dot": ["dot"],
    }
    for name, terms in keywords.items():
        if any(term in command_lower for term in terms):
            return name
    return None


def _format_simple_response(df: pd.DataFrame, command: str) -> Optional[str]:
    """
    Handle straightforward pandas queries without hitting the LLM.
    """
    lower = command.lower()
    if ("前" in command and "行" in command) or "head" in lower:
        numbers = re.findall(r"\d+", command)
        n = int(numbers[0]) if numbers else 5
        return df.head(n).to_string()

    if "列" in command or "columns" in lower:
        columns = ", ".join(df.columns)
        return f"列名：{columns}"

    if "摘要" in command or "summary" in lower or "describe" in lower:
        return df.describe(include="all").to_string()

    return None


def _standardize_features(df: pd.DataFrame) -> Tuple[pd.DataFrame, str]:
    numeric_cols = df.select_dtypes(include=["number"]).columns
    if numeric_cols.empty:
        return df, "未找到可标准化的数值特征。"

    scaler = StandardScaler()
    scaled = scaler.fit_transform(df[numeric_cols])
    new_df = df.copy()
    new_df[numeric_cols] = scaled
    preview = new_df.head(5).to_string()
    message = (
        f"已对数值特征进行标准化，列：{', '.join(numeric_cols)}。\n"
        f"预览（前5行）：\n```\n{preview}\n```"
    )
    return new_df, message


async def process_user_command(
    command: str, manager: ConversationManager, api_key: str, model_name: str = "deepseek-chat"
) -> str:
    """
    Main entry point for processing a user command.
    """
    command_lower = command.lower()
    is_load_intent = "加载" in command or "load" in command_lower

    if is_load_intent:
        dataset_name = _detect_dataset_name(command_lower)
        if dataset_name is None:
            system_note = (
                "用户请求加载数据集，但未匹配到名称。请结合可用列表引导其重新选择。"
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": DATASET_CATALOG},
                {"role": "system", "content": system_note},
            ]
            messages.extend(manager.get_history())
            messages.append({"role": "user", "content": command})
            response = await invoke_deepseek(api_key, messages, model_name=model_name)
            manager.add_message("user", command)
            manager.add_message("assistant", response)
            return response

        # Reset context when switching datasets.
        manager.clear_context()

        try:
            if dataset_name == "dot":
                dot_path = Path(__file__).parent / "data.dot"
                df, descr = data_loader.load_dot_dataset(str(dot_path))
            else:
                df, descr = data_loader.load_sklearn_dataset(dataset_name)
            manager.set_data(df, dataset_name)
            manager.set_data(df, dataset_name)
            summary = (
                f"数据集 {dataset_name} 已加载。形状：{df.shape}。"
                f"示例列：{', '.join(map(str, df.columns[:5]))}。"
                "请用中文总结加载结果并给出下一步（清洗、EDA、建模等）建议，引导用户选择。"
            )
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "system", "content": DATASET_CATALOG},
                {"role": "system", "content": summary},
            ]
            messages.extend(manager.get_history())
            messages.append({"role": "user", "content": command})
            response = await invoke_deepseek(
                api_key, messages, model_name=model_name, include_reasoning=True
            )
        except Exception as exc:
            response = f"加载数据集时出错：{exc}"

        manager.add_message("user", command)
        manager.add_message("assistant", response)
        return response

    # Non-load commands: must have existing data.
    df, dataset_name = manager.get_data()
    if df is None:
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "system", "content": DATASET_CATALOG},
            {"role": "system", "content": "当前尚未加载任何数据集，请引导用户先选择并加载。"},
        ]
        messages.extend(manager.get_history())
        messages.append({"role": "user", "content": command})
        response = await invoke_deepseek(
            api_key, messages, model_name=model_name, include_reasoning=True
        )
        manager.add_message("user", command)
        manager.add_message("assistant", response)
        return response

    # Local standardization handling to avoid模型调用失败
    if "标准化" in command or "归一化" in command or "scal" in command_lower:
        new_df, msg = _standardize_features(df)
        manager.set_data(new_df, dataset_name or "当前数据集")
        manager.add_message("user", command)
        manager.add_message("assistant", msg)
        return msg

    data_summary = (
        f"当前已加载数据集：{dataset_name}，形状：{df.shape}，"
        f"示例列：{', '.join(map(str, df.columns[:5]))}。"
    )
    messages: List[Dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": DATASET_CATALOG},
        {"role": "system", "content": data_summary},
    ]
    messages.extend(manager.get_history())
    messages.append({"role": "user", "content": command})

    try:
        response = await invoke_deepseek(
            api_key, messages, model_name=model_name, include_reasoning=True
        )
    except Exception as exc:
        response = f"调用模型时出现问题：{exc}"

    manager.add_message("user", command)
    manager.add_message("assistant", response)
    return response
