"""
Core agent logic for handling user commands and managing conversation state.
Student role: 大模型扮演不懂机器学习的学生，用户是老师。
所有对话由大模型生成，智能体只负责状态管理和执行操作。
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
import json
from typing import Any, Dict, List, Optional, Tuple

import httpx
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.model_selection import train_test_split
from sklearn.linear_model import LogisticRegression, LinearRegression
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.metrics import accuracy_score, mean_squared_error, confusion_matrix
import numpy as np

from . import data_loader


logger = logging.getLogger(__name__)


STUDENT_SYSTEM_PROMPT = """你是一个正在学习机器学习的学生，对机器学习只有基础了解，需要老师（用户）的指导。保持学生的语气，但执行动作要果断高效：收到指令先执行（调用模型/代码），再用简短学生口吻汇报结果，不要啰嗦或反复确认。

你的角色特点：
1. 谦虚好学：你不太懂机器学习，需要老师一步步指导（口头表达保持学生身份）
2. 执行者角色：指令明确时直接动手，快速给出结果
3. 如需澄清再提问，否则不拖延
4. 展示关键代码/结果，语言简短
5. 请求反馈：完成一步后简短问老师下一步

你拥有以下能力，可以在老师指导下执行：
1. 加载常见的数据集（Iris, Wine, Breast Cancer, California Housing, dot）
2. 进行基本的数据查看和预处理
3. 实现简单的机器学习算法
4. 评估模型性能

你的回复风格：
1. 使用自然、口语化的中文，保持学生口吻但简洁
2. 先报执行结果，再简短说明做了什么
3. 只在必要时提问澄清，不要过度寒暄
4. 询问老师反馈和下一步指导

记住：你是学生，老师是专家。按照老师的指令执行，展示结果，然后请求下一步指导。

可视化约束（避免返回前端无法显示的代码块）：
- 前端会自动生成/渲染图表，你不要返回 matplotlib/pyecharts/echarts 的绘图代码，也不要用「执行结果」包裹重复内容。
- 当老师要求画图（折线/柱状/散点/直方图/箱线图/混淆矩阵/特征重要性/准确率对比等），直接用自然语言总结图表含义，并明确指出“已生成图表，将由前端 ECharts 渲染”，不要返回代码/图片/base64。
- 如果需要特定字段（如使用哪些特征、按索引还是按类别），先确认；否则默认按样本索引和常用数值特征生成。
- 避免重复的“执行结果”标签，直接给出简短结论和图表已生成的提示。
"""


class ConversationManager:
    """
    Stores dialogue history and the currently loaded dataset.
    """

    def __init__(self) -> None:
        self.history: List[Dict[str, str]] = []
        self.current_data: Optional[pd.DataFrame] = None
        self.current_dataset_name: Optional[str] = None
        self.current_X: Optional[pd.DataFrame] = None
        self.current_y: Optional[pd.Series] = None
        self.X_train: Optional[pd.DataFrame] = None
        self.X_test: Optional[pd.DataFrame] = None
        self.y_train: Optional[pd.Series] = None
        self.y_test: Optional[pd.Series] = None
        self.current_model: Optional[Any] = None
        self.current_model_name: Optional[str] = None
        self.current_task_type: Optional[str] = None  # 'classification' or 'regression'
        self.last_eval_true: Optional[np.ndarray] = None
        self.last_eval_pred: Optional[np.ndarray] = None
        self.last_eval_proba: Optional[np.ndarray] = None
        self.metric_history: Dict[str, Dict[str, float]] = {}  # model_name -> metrics

    def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        logger.debug("Message added role=%s content_preview=%s", role, content[:200])

    def get_history(self) -> List[Dict[str, str]]:
        return list(self.history)

    def set_data(self, df: pd.DataFrame, name: str) -> None:
        self.current_data = df
        self.current_dataset_name = name
        # 尝试自动识别任务类型
        if name in ['iris', 'wine', 'breast_cancer']:
            self.current_task_type = 'classification'
        elif name == 'california_housing':
            self.current_task_type = 'regression'
        logger.info("Dataset set name=%s shape=%s task=%s", name, df.shape, self.current_task_type)

    def get_data(self) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        return self.current_data, self.current_dataset_name

    def clear_context(self) -> None:
        self.history.clear()
        self.current_data = None
        self.current_dataset_name = None
        self.current_X = None
        self.current_y = None
        self.X_train = None
        self.X_test = None
        self.y_train = None
        self.y_test = None
        self.current_model = None
        self.current_model_name = None
        self.current_task_type = None
        self.last_eval_true = None
        self.last_eval_pred = None
        self.last_eval_proba = None
        self.metric_history = {}
        logger.info("Conversation context cleared")

    def set_features_target(self, X: pd.DataFrame, y: pd.Series) -> None:
        """设置特征和目标变量"""
        self.current_X = X
        self.current_y = y
        logger.info("Features/target set X_shape=%s y_shape=%s", X.shape, y.shape)

    def split_data(self, test_size: float = 0.2, random_state: int = 42) -> str:
        """分割数据集为训练集和测试集"""
        if self.current_X is None or self.current_y is None:
            return "错误：请先设置特征和目标变量"

        self.X_train, self.X_test, self.y_train, self.y_test = train_test_split(
            self.current_X, self.current_y,
            test_size=test_size,
            random_state=random_state
        )

        logger.info("Data split with test_size=%.2f train_shape=%s test_shape=%s", test_size, self.X_train.shape, self.X_test.shape)
        return f"数据分割完成。训练集: {self.X_train.shape}，测试集: {self.X_test.shape}"

    def set_model(self, model: Any) -> None:
        """设置当前模型"""
        self.current_model = model
        self.current_model_name = type(model).__name__
        logger.info("Model set to %s", self.current_model_name)

    def record_metric(self, metric_name: str, value: float) -> None:
        """记录当前模型的指标，便于后续对比图表"""
        if not self.current_model:
            return
        model_name = self.current_model_name or type(self.current_model).__name__
        metrics = self.metric_history.get(model_name, {})
        metrics[metric_name] = float(value)
        self.metric_history[model_name] = metrics
        logger.info("Metric recorded model=%s %s=%.4f", model_name, metric_name, value)

    def train_model(self) -> str:
        """训练当前模型"""
        if self.current_model is None:
            return "错误：请先设置模型"
        if self.X_train is None or self.y_train is None:
            return "错误：请先分割数据"

        self.current_model.fit(self.X_train, self.y_train)
        logger.info("Model training finished model=%s", type(self.current_model).__name__)
        return "模型训练完成"

    def evaluate_model(self) -> Tuple[str, Any]:
        """评估当前模型"""
        if self.current_model is None:
            return "错误：请先设置并训练模型", None
        if self.X_test is None or self.y_test is None:
            return "错误：请先分割数据", None

        y_pred = self.current_model.predict(self.X_test)
        self.last_eval_true = np.array(self.y_test)
        self.last_eval_pred = np.array(y_pred)
        self.last_eval_proba = None

        if self.current_task_type == 'classification':
            # 尝试保存概率，用于 ROC/PR 等
            if hasattr(self.current_model, "predict_proba"):
                try:
                    proba = self.current_model.predict_proba(self.X_test)
                    # 二分类取正类概率；多分类保留完整矩阵
                    self.last_eval_proba = np.array(proba)
                except Exception:
                    self.last_eval_proba = None

            accuracy = accuracy_score(self.y_test, y_pred)
            self.record_metric("accuracy", accuracy)
            logger.info("Model evaluated type=classification accuracy=%.4f", accuracy)
            return f"分类准确率: {accuracy:.4f}", y_pred
        elif self.current_task_type == 'regression':
            mse = mean_squared_error(self.y_test, y_pred)
            self.record_metric("mse", mse)
            logger.info("Model evaluated type=regression mse=%.4f", mse)
            return f"均方误差 (MSE): {mse:.4f}", y_pred
        else:
            logger.info("Model evaluated without task type, returning predictions preview")
            return f"预测结果: {y_pred[:10]}... (显示前10个)", y_pred


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
        logger.info("Calling DeepSeek model=%s messages=%d timeout=%.1fs stream=%s", model_name, len(messages), timeout_s, payload["stream"])
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            response.raise_for_status()

            # Stream response chunks and assemble content
            content = await _consume_stream_response(response)
            if content:
                return content

            # Fallback: non-stream or empty stream
            data = await response.json()

    try:
        message = data["choices"][0]["message"]
        content = message.get("content", "")
        return content
    except (KeyError, IndexError) as exc:
        logger.exception("Unexpected DeepSeek response structure")
        raise RuntimeError(f"Unexpected DeepSeek response: {data}") from exc


async def _consume_stream_response(response: httpx.Response) -> str:
    """Consume streaming SSE-like response and concatenate content."""
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


def _extract_test_size(command: str) -> float:
    """从命令中提取测试集比例"""
    numbers = re.findall(r"0?\.?\d+", command)
    if numbers:
        try:
            test_size = float(numbers[0])
            if test_size >= 1:  # 如果是整数百分比
                test_size = test_size / 100
            return min(0.9, max(0.1, test_size))  # 限制在0.1-0.9之间
        except:
            pass
    return 0.2


def _extract_model_type(command_lower: str) -> Optional[Tuple[str, Any]]:
    """从命令中提取模型类型"""
    if "逻辑" in command_lower or "logistic" in command_lower:
        return "逻辑回归", LogisticRegression()
    elif "线性" in command_lower or "linear" in command_lower:
        return "线性回归", LinearRegression()
    elif "决策树" in command_lower or "decision" in command_lower:
        if "回归" in command_lower:
            return "决策树回归", DecisionTreeRegressor()
        else:
            return "决策树分类", DecisionTreeClassifier()
    elif "随机森林" in command_lower or "random" in command_lower:
        if "回归" in command_lower:
            return "随机森林回归", RandomForestRegressor()
        else:
            return "随机森林分类", RandomForestClassifier()
    return None


def _build_context_string(manager: ConversationManager) -> str:
    """构建当前上下文的字符串描述"""
    context_parts = []

    if manager.current_dataset_name:
        context_parts.append(f"当前加载的数据集: {manager.current_dataset_name}")

    if manager.current_data is not None:
        context_parts.append(f"数据形状: {manager.current_data.shape} (行×列)")
        context_parts.append(f"数据列名: {', '.join(manager.current_data.columns.tolist())}")

    if manager.current_X is not None and manager.current_y is not None:
        context_parts.append(f"已设置特征矩阵X: {manager.current_X.shape}")
        context_parts.append(f"已设置目标变量y: {manager.current_y.shape}")

    if manager.X_train is not None:
        context_parts.append(f"已分割数据 - 训练集: {manager.X_train.shape}, 测试集: {manager.X_test.shape}")

    if manager.current_model is not None:
        model_name = type(manager.current_model).__name__
        context_parts.append(f"当前模型: {model_name}")
        # 检查是否已训练
        try:
            if hasattr(manager.current_model, 'coef_'):
                context_parts.append("模型状态: 已训练")
            else:
                context_parts.append("模型状态: 未训练")
        except:
            context_parts.append("模型状态: 未训练")

    if manager.current_task_type:
        context_parts.append(f"任务类型: {manager.current_task_type}")

    if not context_parts:
        return "当前状态: 未加载数据"

    return "当前状态:\n" + "\n".join([f"- {part}" for part in context_parts])


def _find_sepal_length_column(df: pd.DataFrame) -> Optional[str]:
    for col in df.columns:
        low = col.lower()
        if "sepal length" in low or ("花萼" in low and ("length" in low or "长" in low)):
            return col
    return None


def _get_numeric_columns(df: pd.DataFrame) -> List[str]:
    return df.select_dtypes(include=["number"]).columns.tolist()


def _match_columns_by_name(command_lower: str, columns: List[str]) -> List[str]:
    matched = []
    for col in columns:
        if col.lower() in command_lower:
            matched.append(col)
    return matched


def _build_histogram(df: pd.DataFrame, col: str, bins: int = 20) -> Dict[str, Any]:
    data = df[col].dropna().to_numpy()
    counts, edges = np.histogram(data, bins=bins)
    centers = 0.5 * (edges[1:] + edges[:-1])
    return {
        "type": "bar",
        "chartSubtype": "histogram",
        "title": f"{col} 分布（直方图）",
        "xLabel": col,
        "yLabel": "频数",
        "series": [
            {
                "name": col,
                "x": centers.tolist(),
                "y": counts.tolist(),
            }
        ],
    }


def _build_scatter(df: pd.DataFrame, col_x: str, col_y: str, color_col: Optional[str] = None) -> Dict[str, Any]:
    x = df[col_x].to_numpy()
    y = df[col_y].to_numpy()
    series = []
    if color_col and color_col in df.columns:
        groups = df[color_col].astype(str)
        for name, grp in df.groupby(color_col):
            series.append({
                "name": str(name),
                "points": grp[[col_x, col_y]].to_numpy().tolist(),
            })
    else:
        series.append({"name": f"{col_y} vs {col_x}", "points": list(map(list, zip(x, y)))})

    return {
        "type": "scatter",
        "title": f"{col_y} vs {col_x}",
        "xLabel": col_x,
        "yLabel": col_y,
        "series": series,
    }


def _build_feature_importance(manager: ConversationManager) -> Optional[Dict[str, Any]]:
    model = manager.current_model
    if model is None or manager.current_X is None:
        return None

    feature_names = list(manager.current_X.columns)
    importances: Optional[np.ndarray] = None

    if hasattr(model, "feature_importances_"):
        importances = np.array(model.feature_importances_)
    elif hasattr(model, "coef_"):
        coef = np.array(model.coef_)
        if coef.ndim == 1:
            importances = np.abs(coef)
        elif coef.ndim == 2:
            importances = np.abs(coef).mean(axis=0)

    if importances is None:
        return None

    # 对齐长度
    n = min(len(feature_names), len(importances))
    feature_names = feature_names[:n]
    importances = importances[:n]
    sorted_idx = np.argsort(importances)[::-1]
    feature_names = [feature_names[i] for i in sorted_idx]
    importances = importances[sorted_idx]

    return {
        "type": "bar",
        "chartSubtype": "feature_importance",
        "title": "特征重要性",
        "xLabel": "特征",
        "yLabel": "重要性",
        "series": [
            {
                "name": "importance",
                "x": feature_names,
                "y": importances.tolist(),
            }
        ],
    }


def _build_confusion_matrix(manager: ConversationManager) -> Optional[Dict[str, Any]]:
    if manager.current_task_type != "classification":
        return None
    if manager.last_eval_true is None or manager.last_eval_pred is None:
        return None
    true = manager.last_eval_true
    pred = manager.last_eval_pred
    labels = np.unique(np.concatenate([true, pred]))
    cm = confusion_matrix(true, pred, labels=labels)
    data = []
    for i, actual in enumerate(labels):
        for j, predicted in enumerate(labels):
            data.append([j, i, int(cm[i, j])])
    labels_list = [str(l) for l in labels.tolist()]
    return {
        "type": "heatmap",
        "chartSubtype": "confusion_matrix",
        "title": "混淆矩阵",
        "xCategories": [f"预测 {l}" for l in labels_list],
        "yCategories": [f"真实 {l}" for l in labels_list],
        "matrix": cm.tolist(),
        "data": data,
    }


def _build_accuracy_comparison(manager: ConversationManager) -> Optional[Dict[str, Any]]:
    if not manager.metric_history:
        return None
    entries = []
    for model_name, metrics in manager.metric_history.items():
        if "accuracy" in metrics:
            entries.append((model_name, metrics["accuracy"]))
    if not entries:
        return None
    # 只取前 10 个，避免过长
    entries = entries[:10]
    model_names = [e[0] for e in entries]
    accuracies = [e[1] for e in entries]
    return {
        "type": "bar",
        "chartSubtype": "accuracy_comparison",
        "title": "模型准确率对比",
        "xLabel": "模型",
        "yLabel": "准确率",
        "series": [
            {
                "name": "accuracy",
                "x": model_names,
                "y": accuracies,
            }
        ],
    }


def _build_all_numeric_trend(df: pd.DataFrame, max_cols: int = 6) -> Optional[Dict[str, Any]]:
    numeric_cols = _get_numeric_columns(df)
    # 尝试排除 target 列
    numeric_cols = [c for c in numeric_cols if "target" not in c.lower()]
    if not numeric_cols:
        return None
    numeric_cols = numeric_cols[:max_cols]
    series = []
    x_vals = list(range(len(df)))
    for col in numeric_cols:
        series.append({"name": col, "x": x_vals, "y": df[col].tolist()})
    return {
        "type": "line",
        "chartSubtype": "multi_feature_trend",
        "title": "数值特征变化趋势（按样本索引）",
        "xLabel": "样本索引",
        "yLabel": "特征值",
        "series": series,
    }


def _infer_chart_request(command_lower: str, manager: ConversationManager) -> Optional[Dict[str, Any]]:
    """
    Inspect the command and current state to decide which chart to build.
    Returns a payload dict or None.
    """
    df = manager.current_data
    if df is None or df.empty:
        return None

    # 直方图 / 分布
    if any(k in command_lower for k in ["直方", "hist", "分布"]):
        numeric_cols = _get_numeric_columns(df)
        if not numeric_cols:
            return None
        matched = _match_columns_by_name(command_lower, numeric_cols)
        col = matched[0] if matched else numeric_cols[0]
        return _build_histogram(df, col)

    # 散点图
    if any(k in command_lower for k in ["散点", "scatter", "相关", "关系"]):
        numeric_cols = _get_numeric_columns(df)
        if len(numeric_cols) >= 2:
            matched = _match_columns_by_name(command_lower, numeric_cols)
            if len(matched) >= 2:
                col_x, col_y = matched[:2]
            else:
                col_x, col_y = numeric_cols[0], numeric_cols[1]
            color_col = None
            # 如果存在分类标签列，尝试用于分色
            if manager.current_y is not None and manager.current_task_type == "classification":
                color_col = manager.current_y.name if hasattr(manager.current_y, "name") else None
            return _build_scatter(df, col_x, col_y, color_col)

    # 特征重要性
    if any(k in command_lower for k in ["重要性", "importance", "权重", "系数"]):
        fi = _build_feature_importance(manager)
        if fi:
            return fi

    # 混淆矩阵
    if any(k in command_lower for k in ["混淆", "confusion"]):
        cm = _build_confusion_matrix(manager)
        if cm:
            return cm

    # 模型准确率对比
    if any(k in command_lower for k in ["准确率", "accuracy"]) and any(k in command_lower for k in ["对比", "比较", "comparison", "compare"]):
        acc_chart = _build_accuracy_comparison(manager)
        if acc_chart:
            return acc_chart

    # 多特征折线趋势
    trend_scopes = [
        "各个变量", "所有特征", "所有变量", "全体特征", "全体变量",
        "多特征", "多变量", "all features", "all variables", "feature trend", "features",
        "四个特征", "四个变量", "全部特征", "全部变量", "特征变化", "变量变化",
    ]
    trend_intent = ["折线", "趋势", "line", "trend", "变化趋势", "趋势图"]
    if any(k in command_lower for k in trend_scopes) and any(k in command_lower for k in trend_intent):
        trend_chart = _build_all_numeric_trend(df)
        if trend_chart:
            return trend_chart
    # 宽松兜底：如果有“趋势”关键词且存在数值列，默认返回多特征趋势
    if any(k in command_lower for k in trend_intent):
        trend_chart = _build_all_numeric_trend(df)
        if trend_chart:
            return trend_chart

    # fallback: sepal length 折线
    if _needs_sepal_chart(command_lower, df):
        return _build_sepal_length_chart(df)

    return None




def _build_sepal_length_chart(df: pd.DataFrame) -> Optional[Dict[str, Any]]:
    col = _find_sepal_length_column(df)
    if col is None:
        return None
    x_vals = list(range(len(df)))
    y_vals = df[col].tolist()
    return {
        "type": "line",
        "title": "Sepal Length变化趋势（按样本索引）",
        "xLabel": "样本索引",
        "yLabel": col,
        "series": [
            {
                "name": col,
                "x": x_vals,
                "y": y_vals,
            }
        ],
    }


def _needs_sepal_chart(command_lower: str, df: pd.DataFrame) -> bool:
    if df is None or df.empty:
        return False
    wants_line = any(word in command_lower for word in ["折线", "line", "趋势", "曲线"])
    wants_sepal = any(word in command_lower for word in ["sepal length", "花萼长度", "花萼长", "sepal"])
    has_col = _find_sepal_length_column(df) is not None
    return wants_line and wants_sepal and has_col


async def process_user_command(
    command: str, manager: ConversationManager, api_key: str, model_name: str = "deepseek-chat"
) -> Dict[str, Any]:
    """
    Main entry point for processing a user command.
    Student mode: 大模型是学生，等待老师指令，所有对话由大模型生成。
    """
    logger.info("Processing command: %s", command)
    command_lower = command.lower()

    # 添加用户消息到历史
    manager.add_message("user", command)

    # 构建系统提示和上下文
    context_str = _build_context_string(manager)
    system_message = f"{STUDENT_SYSTEM_PROMPT}\n\n{context_str}"

    # 检测并执行操作，但不生成回复
    operation_result = ""
    chart_payload: Optional[Dict[str, Any]] = None

    # 1. 检测加载数据集意图
    is_load_intent = any(word in command_lower for word in ["加载", "load", "使用", "选择", "数据集", "导入"])

    if is_load_intent:
        dataset_name = _detect_dataset_name(command_lower)
        if dataset_name:
            logger.info("Load intent detected dataset=%s", dataset_name)
            try:
                manager.clear_context()
                if dataset_name == "dot":
                    dot_path = Path(__file__).parent / "data.dot"
                    df, descr = data_loader.load_dot_dataset(str(dot_path))
                else:
                    df, descr = data_loader.load_sklearn_dataset(dataset_name)

                manager.set_data(df, dataset_name)
                operation_result = f"已执行操作: 成功加载数据集 '{dataset_name}'，形状: {df.shape}"
                logger.info("Dataset loaded name=%s shape=%s", dataset_name, df.shape)
            except Exception as exc:
                operation_result = f"执行操作时出错: 加载数据集失败 - {exc}"
                logger.exception("Failed to load dataset %s", dataset_name)
        else:
            operation_result = "未识别到具体的数据集名称"
            logger.warning("Load intent detected but dataset name not recognized")

    # 2. 检测数据查看操作
    elif manager.current_data is not None:
        if any(word in command_lower for word in ["前", "行", "head", "查看", "显示"]):
            # 提取要查看的行数
            numbers = re.findall(r"\d+", command)
            n = int(numbers[0]) if numbers else 5
            n = min(n, 20)  # 限制最大行数

            head_data = manager.current_data.head(n)
            operation_result = f"已执行操作: 查看数据前{n}行\n{head_data.to_string()}"
            logger.info("Head operation executed rows=%d", n)

        elif any(word in command_lower for word in ["列", "columns", "特征"]):
            columns = manager.current_data.columns.tolist()
            operation_result = f"已执行操作: 查看数据列\n列名: {', '.join(columns)}"
            logger.info("Columns inspected count=%d", len(columns))

        elif any(word in command_lower for word in ["描述", "describe", "统计", "摘要"]):
            desc = manager.current_data.describe(include="all")
            operation_result = f"已执行操作: 数据统计描述\n{desc.to_string()}"
            logger.info("Describe operation executed")

        elif any(word in command_lower for word in ["形状", "shape", "大小"]):
            shape = manager.current_data.shape
            operation_result = f"已执行操作: 查看数据形状\n数据形状: {shape[0]}行 × {shape[1]}列"
            logger.info("Shape inspected shape=%s", shape)

    # 3. 检测数据预处理操作
    if manager.current_data is not None:
        if any(word in command_lower for word in ["标准化", "归一化", "scal", "normal"]):
            numeric_cols = manager.current_data.select_dtypes(include=["number"]).columns
            if not numeric_cols.empty:
                scaler = StandardScaler()
                scaled = scaler.fit_transform(manager.current_data[numeric_cols])
                new_df = manager.current_data.copy()
                new_df[numeric_cols] = scaled
                manager.set_data(new_df, manager.current_dataset_name)
                operation_result = f"已执行操作: 数据标准化\n标准化列: {', '.join(numeric_cols)}\n标准化后前3行:\n{new_df.head(3).to_string()}"
                logger.info("Standardization applied columns=%s", ", ".join(numeric_cols))
            else:
                operation_result = "执行操作: 未找到数值列进行标准化"
                logger.warning("Standardization requested but no numeric columns found")

    # 4. 检测特征/目标变量设置
    if manager.current_data is not None:
        set_target = False
        target_col = None

        if any(word in command_lower for word in ["目标", "target", "y", "标签"]):
            # 尝试从命令中提取目标列
            for col in manager.current_data.columns:
                if col.lower() in command_lower:
                    target_col = col
                    break

            # 如果未指定，使用默认或最后一列
            if target_col is None:
                if "target" in manager.current_data.columns:
                    target_col = "target"
                else:
                    target_col = manager.current_data.columns[-1]

            feature_cols = [col for col in manager.current_data.columns if col != target_col]

            if target_col in manager.current_data.columns:
                X = manager.current_data[feature_cols]
                y = manager.current_data[target_col]
                manager.set_features_target(X, y)
                operation_result = f"已执行操作: 设置特征和目标变量\n特征X: {X.shape}, 列: {', '.join(feature_cols)}\n目标y: {y.shape}, 列: {target_col}"
                set_target = True

        # 如果命令明确指定了特征列
        if not set_target and any(word in command_lower for word in ["特征", "feature", "x"]):
            # 简化处理：将所有列都作为特征，最后一个作为目标
            if manager.current_data is not None and len(manager.current_data.columns) > 1:
                feature_cols = manager.current_data.columns[:-1]
                target_col = manager.current_data.columns[-1]
                X = manager.current_data[feature_cols]
                y = manager.current_data[target_col]
                manager.set_features_target(X, y)
                operation_result = f"已执行操作: 设置特征和目标变量\n特征X: {X.shape}, 列: {', '.join(feature_cols)}\n目标y: {y.shape}, 列: {target_col}"
                logger.info("Features/target auto-set target=%s", target_col)

    # 5. 检测数据分割操作
    if manager.current_X is not None and manager.current_y is not None:
        if any(word in command_lower for word in ["分割", "划分", "split", "训练集", "测试集"]):
            test_size = _extract_test_size(command)
            result = manager.split_data(test_size=test_size)
            operation_result = f"已执行操作: 数据分割\n{result}"

    # 6. 检测模型设置操作
    model_info = _extract_model_type(command_lower)
    if model_info:
        model_name_str, model = model_info
        manager.set_model(model)
        operation_result = f"已执行操作: 设置模型\n模型类型: {model_name_str}"
        logger.info("Model selected %s", model_name_str)

    # 7. 检测模型训练操作
    elif any(word in command_lower for word in ["训练", "fit", "train"]):
        if manager.current_model is not None:
            result = manager.train_model()
            operation_result = f"已执行操作: 模型训练\n{result}"
        else:
            operation_result = "执行操作: 请先设置模型类型"
            logger.warning("Train requested but model is not set")

    # 8. 检测模型评估操作
    elif any(word in command_lower for word in ["评估", "测试", "准确", "误差", "evaluate", "score"]):
        if manager.current_model is not None:
            result, predictions = manager.evaluate_model()
            if predictions is not None:
                operation_result = f"已执行操作: 模型评估\n{result}"
        else:
            operation_result = "执行操作: 请先训练模型"
            logger.warning("Evaluation requested but model not trained")

    # 构建完整的消息列表发送给大模型
    messages = [{"role": "system", "content": system_message}]

    # 添加历史对话（排除当前的用户消息，因为它已经在上下文中）
    history = manager.get_history()
    if len(history) > 1:  # 至少有当前用户消息和前一条消息
        messages.extend(history[:-1])  # 添加除最后一条（当前用户消息）外的历史

    # 添加操作结果作为系统消息（如果有）
    if operation_result:
        messages.append({"role": "system", "content": f"刚才执行的操作结果:\n{operation_result}"})
        first_line = operation_result.splitlines()[0] if operation_result else ""
        logger.info("Operation result attached to context: %s", first_line)

    # 添加当前用户消息
    messages.append({"role": "user", "content": command})

    try:
        # 调用大模型生成回复
        response = await invoke_deepseek(
            api_key, messages, model_name=model_name, include_reasoning=False
        )

        # 添加助手回复到历史
        manager.add_message("assistant", response)
        logger.info("DeepSeek reply generated length=%d", len(response))

        # 根据意图尝试生成图表（包含通用和 sepal length 特判）
        chart_payload = _infer_chart_request(command_lower, manager)
        if chart_payload:
            logger.info(
                "Chart payload attached type=%s subtype=%s title=%s",
                chart_payload.get("type"),
                chart_payload.get("chartSubtype"),
                chart_payload.get("title"),
            )

        result: Dict[str, Any] = {"reply": response}
        if chart_payload:
            result["chart"] = chart_payload
        return result

    except Exception as exc:
        error_msg = f"抱歉老师，处理您的指令时出错了：{exc}\n您能再解释一下吗？"
        manager.add_message("assistant", error_msg)
        logger.exception("Error while processing command")
        return {"reply": error_msg}
