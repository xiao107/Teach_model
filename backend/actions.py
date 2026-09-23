"""
Action handlers: execute LLM-declared actions against the session state.

Each handler returns a markdown appendix to append to the student's reply.
The `plot` action additionally returns a chart payload for the frontend.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

import pandas as pd
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor, RandomForestClassifier, RandomForestRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression
from sklearn.metrics import accuracy_score, confusion_matrix, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.neighbors import KNeighborsClassifier, KNeighborsRegressor
from sklearn.preprocessing import LabelEncoder
from sklearn.svm import SVC, SVR
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor

from backend import data_loader
from backend import charts
from backend.state import ConversationManager

logger = logging.getLogger(__name__)


def execute_action(
    action: str,
    params: Dict[str, Any],
    manager: ConversationManager,
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Execute a single action. Returns (markdown_appendix, chart_payload).
    The appendix should be appended to the student's reply.
    """
    handlers = {
        "plot": _action_plot,
        "load": _action_load,
        "preview": _action_preview,
        "check_missing": _action_check_missing,
        "fill_missing": _action_fill_missing,
        "encode": _action_encode,
        "split": _action_split,
        "train": _action_train,
        "evaluate": _action_evaluate,
        # TASK-206: convenience aliases (LLM may emit these directly)
        "knn_train": lambda p, m: _action_train({**p, "model": "knn"}, m),
        "svm_train": lambda p, m: _action_train({**p, "model": "svm"}, m),
        "gbt_train": lambda p, m: _action_train({**p, "model": "gbt"}, m),
    }
    handler = handlers.get(action)
    if handler is None:
        return f"\n\n❌ 不支持的操作类型：{action}", None
    return handler(params or {}, manager)


# ---------------------------------------------------------------------- data actions

def _action_load(params: Dict[str, Any], manager: ConversationManager) -> Tuple[str, None]:
    dataset_name = str(params.get("dataset", "")).lower()
    if dataset_name not in ("iris", "wine", "breast_cancer", "california_housing"):
        return "\n\n❌ 不支持的数据集，可用：iris / wine / breast_cancer / california_housing", None
    try:
        df, _descr = data_loader.load_sklearn_dataset(dataset_name)
        manager.set_data(df, dataset_name)
        cols = df.columns.tolist()
        col_text = ", ".join(cols) if len(cols) <= 6 else f"{', '.join(cols[:5])}... (共{len(cols)}列)"
        text = (
            "\n\n---\n\n**✓ 数据集加载成功**\n\n"
            f"- **名称**: {dataset_name}\n"
            f"- **样本数**: {df.shape[0]}\n"
            f"- **特征数**: {df.shape[1]}\n"
            f"- **列名**: {col_text}\n"
        )
        return text, None
    except Exception as exc:
        logger.exception("Failed to load dataset")
        return f"\n\n❌ 加载失败：{exc}", None


def _action_preview(params: Dict[str, Any], manager: ConversationManager) -> Tuple[str, None]:
    if manager.current_data is None:
        return "\n\n❌ 还没有加载数据集，请先加载数据。", None

    df = manager.current_data
    rows = int(params.get("rows", 5))
    max_cols = int(params.get("max_cols", 10))  # wide tables: show first N columns

    total_cols = df.shape[1]
    col_note = ""
    show_df = df
    if total_cols > max_cols:
        # 目标列（target/label 等）教学上最关键，裁剪时始终保留在末尾
        target_cols = [c for c in df.columns if str(c).lower() in ("target", "target_label", "label", "y")]
        feature_cols = [c for c in df.columns if c not in target_cols]
        keep = feature_cols[: max(0, max_cols - len(target_cols))] + target_cols
        show_df = df[keep]
        omitted = total_cols - len(keep)
        col_note = (
            f"\n\n> 📌 数据集共 **{total_cols} 列**，表格仅展示前 {len(keep)} 列"
            f"（其余 {omitted} 列已省略）。如需查看其他列，可以说\"预览 XX、YY 列\"。\n"
        )

    text = f"\n\n---\n\n**前 {rows} 行数据：**\n\n{show_df.head(rows).to_markdown(index=False)}\n"
    text += col_note
    text += "\n**数值列统计：**\n\n"
    numeric_cols = show_df.select_dtypes(include=["number"]).columns.tolist()
    if numeric_cols:
        stats_df = show_df[numeric_cols].describe().T[["count", "mean", "std", "min", "max"]]
        text += stats_df.to_markdown()
    else:
        text += "（无数值列）"
    return text, None


def _action_check_missing(params: Dict[str, Any], manager: ConversationManager) -> Tuple[str, None]:
    if manager.current_data is None:
        return "\n\n❌ 还没有加载数据集。", None

    df = manager.current_data
    missing = df.isnull().sum()
    text = "\n\n---\n\n**缺失值检查结果：**\n\n"
    if missing.sum() == 0:
        text += "✓ 数据集中没有缺失值！\n"
    else:
        missing_pct = (missing / len(df) * 100).round(2)
        missing_df = pd.DataFrame({
            "列名": missing.index,
            "缺失数量": missing.values,
            "缺失比例(%)": missing_pct.values,
        })
        missing_df = missing_df[missing_df["缺失数量"] > 0]
        text += missing_df.to_markdown(index=False)
        text += f"\n\n总缺失值数量：{missing.sum()}\n"
    return text, None


def _action_fill_missing(params: Dict[str, Any], manager: ConversationManager) -> Tuple[str, None]:
    if manager.current_data is None:
        return "\n\n❌ 还没有加载数据集。", None

    df = manager.current_data
    method = params.get("method", "median")
    missing_before = df.isnull().sum().sum()

    if missing_before == 0:
        return "\n\n---\n\n✓ 数据集中没有缺失值，无需填充。", None

    numeric_cols = df.select_dtypes(include=["number"]).columns
    if method == "mean":
        df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].mean())
    elif method == "median":
        df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].median())
    elif method == "mode":
        for col in df.columns:
            mode = df[col].mode()
            df[col] = df[col].fillna(mode.iloc[0] if not mode.empty else df[col])
    elif method == "drop":
        df = df.dropna()
    else:
        return f"\n\n❌ 不支持的填充方法：{method}", None

    manager.current_data = df
    missing_after = df.isnull().sum().sum()
    text = (
        "\n\n---\n\n**✓ 缺失值填充完成**\n\n"
        f"- **填充方法**: {method}\n"
        f"- **填充前缺失值**: {missing_before}\n"
        f"- **填充后缺失值**: {missing_after}\n"
        f"- **当前数据形状**: {df.shape}\n"
    )
    return text, None


def _action_encode(params: Dict[str, Any], manager: ConversationManager) -> Tuple[str, None]:
    if manager.current_data is None:
        return "\n\n❌ 还没有加载数据集。", None

    df = manager.current_data
    columns = params.get("columns", [])
    method = params.get("method", "onehot")

    if not columns:
        return "\n\n❌ 请指定要编码的列名。", None

    existing_cols = [col for col in columns if col in df.columns]
    if not existing_cols:
        return f"\n\n❌ 指定的列不存在。当前列名：{', '.join(df.columns.tolist())}", None

    if method == "onehot":
        df = pd.get_dummies(df, columns=existing_cols, prefix=existing_cols)
    elif method == "label":
        le = LabelEncoder()
        for col in existing_cols:
            df[col] = le.fit_transform(df[col].astype(str))
    else:
        return f"\n\n❌ 不支持的编码方法：{method}", None

    new_col_count = df.shape[1] - manager.current_data.shape[1] + len(existing_cols)
    manager.current_data = df
    text = (
        "\n\n---\n\n**✓ 编码完成**\n\n"
        f"- **编码方法**: {method}\n"
        f"- **编码列**: {', '.join(existing_cols)}\n"
        f"- **编码后特征数**: {df.shape[1]}\n"
        f"- **新增列**: {new_col_count}\n"
    )
    return text, None


def _action_split(params: Dict[str, Any], manager: ConversationManager) -> Tuple[str, None]:
    if manager.current_data is None:
        return "\n\n❌ 还没有加载数据集。", None

    df = manager.current_data
    test_size = float(params.get("test_size", 0.2))
    random_state = int(params.get("random_state", 42))
    target_col = params.get("target")

    if target_col and target_col in df.columns:
        X = df.drop(columns=[target_col])
        y = df[target_col]
    else:
        X = df.iloc[:, :-1]
        y = df.iloc[:, -1]

    # 对非数值特征列做标签编码，保证模型可用
    obj_cols = X.select_dtypes(exclude=["number"]).columns.tolist()
    for col in obj_cols:
        X[col] = X[col].astype("category").cat.codes

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=random_state
    )

    manager.X_train = X_train
    manager.X_test = X_test
    manager.y_train = y_train
    manager.y_test = y_test
    manager.current_X = X
    manager.current_y = y

    text = (
        "\n\n---\n\n**✓ 数据分割完成**\n\n"
        f"- **训练集大小**: {X_train.shape[0]} 样本\n"
        f"- **测试集大小**: {X_test.shape[0]} 样本\n"
        f"- **特征数**: {X_train.shape[1]}\n"
        f"- **测试集比例**: {test_size * 100:.0f}%\n"
        f"- **目标列**: {y.name}\n"
    )
    if obj_cols:
        text += f"- **已自动编码的非数值列**: {', '.join(obj_cols)}\n"
    return text, None


# ---------------------------------------------------------------------- ML actions

MODEL_REGISTRY = {
    "classification": {
        "logistic_regression": LogisticRegression(max_iter=1000),
        "decision_tree": DecisionTreeClassifier(random_state=42),
        "random_forest": RandomForestClassifier(n_estimators=100, random_state=42),
        "knn": KNeighborsClassifier(n_neighbors=5),
        "svm": SVC(random_state=42),
        "gbt": GradientBoostingClassifier(random_state=42),
    },
    "regression": {
        "linear_regression": LinearRegression(),
        "decision_tree": DecisionTreeRegressor(random_state=42),
        "random_forest": RandomForestRegressor(n_estimators=100, random_state=42),
        "knn": KNeighborsRegressor(n_neighbors=5),
        "svm": SVR(),
        "gbt": GradientBoostingRegressor(random_state=42),
    },
}

MODEL_LABELS = {
    "logistic_regression": "逻辑回归",
    "linear_regression": "线性回归",
    "decision_tree": "决策树",
    "random_forest": "随机森林",
    "knn": "K近邻（KNN）",
    "svm": "支持向量机（SVM）",
    "gbt": "梯度提升树（GBDT）",
}


def _ensure_split(manager: ConversationManager) -> bool:
    """Ensure train/test split exists; auto-split with defaults if not."""
    if manager.X_train is not None:
        return True
    appendix, _ = _action_split({"test_size": 0.2, "random_state": 42}, manager)
    return "✓" in appendix


def _action_train(params: Dict[str, Any], manager: ConversationManager) -> Tuple[str, None]:
    model_key = str(params.get("model", "")).lower()

    if not _ensure_split(manager):
        return "\n\n❌ 没有可用的训练数据，且自动分割失败。", None

    task_type = manager.current_task_type or (
        "classification" if manager.y_train.dtype == object or manager.y_train.nunique() <= 20
        else "regression"
    )
    manager.current_task_type = task_type

    available = MODEL_REGISTRY[task_type]
    if not model_key:
        model_key = next(iter(available))
    if model_key not in available:
        return (
            f"\n\n❌ 模型 {model_key} 不适用于当前任务（{task_type}）。"
            f"可用模型：{', '.join(available.keys())}"
        ), None

    try:
        model = available[model_key]
        model.fit(manager.X_train, manager.y_train)
    except Exception as exc:
        logger.exception("Model training failed")
        return f"\n\n❌ 训练失败：{exc}", None

    manager.current_model = model
    manager.current_model_name = model_key

    train_acc = None
    if task_type == "classification":
        train_acc = accuracy_score(manager.y_train, model.predict(manager.X_train))

    text = (
        "\n\n---\n\n**✓ 模型训练完成**\n\n"
        f"- **模型**: {MODEL_LABELS.get(model_key, model_key)}\n"
        f"- **任务类型**: {task_type}\n"
        f"- **训练样本数**: {manager.X_train.shape[0]}\n"
    )
    if train_acc is not None:
        text += f"- **训练集准确率**: {train_acc:.4f}\n"
    text += "\n接下来可以对模型执行 evaluate 操作，查看测试集表现。"
    return text, None


def _action_evaluate(params: Dict[str, Any], manager: ConversationManager) -> Tuple[str, None]:
    if manager.current_model is None:
        return "\n\n❌ 还没有训练模型，请先执行 train 操作。", None

    y_pred = manager.current_model.predict(manager.X_test)
    manager.last_eval_true = manager.y_test.to_numpy()
    manager.last_eval_pred = y_pred

    task_type = manager.current_task_type
    model_label = MODEL_LABELS.get(manager.current_model_name, manager.current_model_name)
    text = f"\n\n---\n\n**✓ 模型评估结果（{model_label}）**\n\n"

    if task_type == "classification":
        acc = accuracy_score(manager.y_test, y_pred)
        manager.last_eval_proba = None
        if hasattr(manager.current_model, "predict_proba"):
            try:
                manager.last_eval_proba = manager.current_model.predict_proba(manager.X_test)
            except Exception:
                pass
        manager.metric_history[manager.current_model_name] = {"accuracy": round(acc, 4)}
        text += f"- **测试集准确率**: {acc:.4f}\n"
        try:
            cm = confusion_matrix(manager.y_test, y_pred)
            cm_df = pd.DataFrame(cm)
            text += f"\n**混淆矩阵**（行=真实值，列=预测值）：\n\n{cm_df.to_markdown()}\n"
        except Exception:
            pass
    else:
        mse = mean_squared_error(manager.y_test, y_pred)
        rmse = float(mse ** 0.5)
        r2 = r2_score(manager.y_test, y_pred)
        manager.metric_history[manager.current_model_name] = {
            "mse": round(float(mse), 4),
            "rmse": round(rmse, 4),
            "r2": round(r2, 4),
        }
        text += (
            f"- **MSE**: {mse:.4f}\n"
            f"- **RMSE**: {rmse:.4f}\n"
            f"- **R²**: {r2:.4f}\n"
        )

    if len(manager.metric_history) > 1:
        text += "\n**历史模型指标对比：**\n\n"
        history_df = pd.DataFrame(manager.metric_history).T
        text += history_df.to_markdown()
        text += "\n"
    return text, None


def _action_plot(params: Dict[str, Any], manager: ConversationManager) -> Tuple[str, Optional[Dict[str, Any]]]:
    chart_payload = charts.create_chart(params, manager)
    if chart_payload:
        return "", chart_payload
    return "\n\n❌ 无法生成图表，请确认已加载数据且指定了有效的列。", None
