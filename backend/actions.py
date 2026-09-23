"""
Action handlers: execute LLM-declared actions against the session state.

Each handler returns a markdown appendix to append to the student's reply.
The `plot` action additionally returns a chart payload for the frontend.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import pandas as pd
from sklearn.base import clone
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
) -> Tuple[str, Optional[Dict[str, Any]], Dict[str, Any]]:
    """
    Execute a single action.

    Returns (markdown_appendix, chart_payload, extra_meta).
    - markdown_appendix: markdown text appended to the student's reply
    - chart_payload: chart dict for the frontend renderer (or None)
    - extra_meta: extra structured fields merged into the SSE result entry
      (P1-1: evaluate 的指标卡片数据走这里，前端不必再解析 markdown)
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
        return f"\n\n❌ 不支持的操作类型：{action}", None, {}
    result = handler(params or {}, manager)
    if len(result) == 3:
        return result
    return result[0], result[1], {}


def _class_labels(manager: ConversationManager, values: Any) -> List[str]:
    """类别索引 -> 人类可读标签（如 0 -> setosa），取不到就原样返回。"""
    mapping: Dict[Any, Any] = {}
    df = manager.current_data
    if df is not None and "target" in df.columns and "target_label" in df.columns:
        try:
            mapping = dict(zip(df["target"].tolist(), df["target_label"].tolist()))
        except Exception:
            mapping = {}
    return [str(mapping.get(v, v)) for v in values]


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
    missing_before = int(df.isnull().sum().sum())

    if missing_before == 0:
        return "\n\n---\n\n✓ 数据集中没有缺失值，无需填充。", None

    # 目标列（及其同源列）不参与填充：把标签填成中位数会污染训练目标
    protected = _label_family_columns(df, manager.current_target_col)
    fill_cols = [c for c in df.columns if c not in protected]

    numeric_cols = [c for c in df[fill_cols].select_dtypes(include=["number"]).columns]
    if method == "mean":
        if numeric_cols:
            df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].mean())
    elif method == "median":
        if numeric_cols:
            df[numeric_cols] = df[numeric_cols].fillna(df[numeric_cols].median())
    elif method == "mode":
        for col in fill_cols:
            mode = df[col].mode()
            if not mode.empty:
                df[col] = df[col].fillna(mode.iloc[0])
    elif method == "drop":
        df = df.dropna(subset=fill_cols) if fill_cols else df
    else:
        return f"\n\n❌ 不支持的填充方法：{method}", None

    manager.current_data = df
    missing_after = int(df.isnull().sum().sum())

    # ---- 真实校验：缺失数没下降就是失败，绝不能报"填充完成" ----
    if missing_after >= missing_before:
        stuck = df.isnull().sum()
        stuck = stuck[stuck > 0]
        detail = "、".join(f"{col}（{int(n)} 个）" for col, n in stuck.items()) or "未知列"
        return (
            f"\n\n❌ 缺失值填充失败：填充后缺失值仍为 {missing_after} 个（填充前 {missing_before} 个）。\n\n"
            f"未能处理的列：{detail}\n\n"
            "常见原因：该列整列都是缺失值，均值/中位数/众数本身也是空值，无法用统计量填充。"
            "请检查是否选错了目标列（用一列全空的数据当标签）。\n"
        ), None

    text = (
        "\n\n---\n\n**✓ 缺失值填充完成**\n\n"
        f"- **填充方法**: {method}\n"
        f"- **填充前缺失值**: {missing_before}\n"
        f"- **填充后缺失值**: {missing_after}\n"
        f"- **当前数据形状**: {df.shape}\n"
    )
    if protected:
        text += f"- **已跳过目标列**: {', '.join(protected)}（避免污染标签）\n"

    if missing_after > 0:
        stuck = df.isnull().sum()
        stuck = stuck[stuck > 0]
        detail = "、".join(f"{col}（{int(n)} 个）" for col, n in stuck.items())
        text += (
            f"\n> ⚠ 仍有 {missing_after} 个缺失值无法用「{method}」填充：{detail}。"
            "这些列整列或大部分为空，需要先确认数据来源是否正确。\n"
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


# ---------------------------------------------------------------------- target column

# 约定目标列名，按优先级排序（先命中且非全空的胜出）
CONVENTIONAL_TARGETS = ("target", "label", "y", "class", "MedHouseVal")

_LABEL_SUFFIXES = ("_label", "_name", "_str")


def _label_family(col: str) -> str:
    """把目标列及其同源列归为同一族。

    iris 同时有 `target`(0/1/2) 和 `target_label`('setosa'...)，二者是同一份标签的
    两种写法。若只把其中一列当 y，另一列留在 X 里，模型会直接"抄答案"（准确率虚高
    到 1.0）。归族后可一次性排除，避免标签泄漏。
    """
    for suffix in _LABEL_SUFFIXES:
        if col.endswith(suffix):
            return col[: -len(suffix)]
    return col


def _label_family_columns(df: pd.DataFrame, target_col: Optional[str]) -> List[str]:
    """目标列同源列（含目标列本身）。target_col 为空时按列名约定兜底。"""
    if not target_col:
        return [c for c in df.columns if str(c).lower() in ("target", "target_label", "label", "y")]
    family = _label_family(str(target_col))
    return [c for c in df.columns if _label_family(str(c)) == family]


def _resolve_target_column(
    df: pd.DataFrame, explicit: Optional[str] = None
) -> Tuple[Optional[str], Optional[str]]:
    """确定目标列，返回 (列名, 错误说明)。

    优先级：显式指定 > 约定列名 > 最后一列。任一候选都必须真实存在且不是整列缺失，
    否则旧版会静默拿一列全 NaN 当标签，训练报出 "Input contains NaN" 后无人能懂。
    """
    def _usable(col: str) -> Tuple[bool, str]:
        if col not in df.columns:
            return False, f"列 {col} 不存在。当前列名：{', '.join(map(str, df.columns))}"
        if df[col].isna().all():
            return False, f"列 {col} 整列都是缺失值（NaN），不能作为目标列"
        return True, ""

    if explicit:
        ok, reason = _usable(str(explicit))
        if not ok:
            # 显式指定失败时给出可用候选，而不是继续往下猜
            candidates = [c for c in CONVENTIONAL_TARGETS if c in df.columns and not df[c].isna().all()]
            hint = f"可用目标列：{', '.join(candidates)}" if candidates else f"最后一列：{df.columns[-1]}"
            return None, f"{reason}。{hint}"
        return str(explicit), None

    for cand in CONVENTIONAL_TARGETS:
        if cand in df.columns and not df[cand].isna().all():
            return cand, None

    last = df.columns[-1]
    if df[last].isna().all():
        all_na = [c for c in CONVENTIONAL_TARGETS if c in df.columns and df[c].isna().all()]
        hint = (
            f"约定目标列 {', '.join(all_na)} 整列都是缺失值"
            if all_na else f"最后一列 {last} 整列都是缺失值"
        )
        return None, f"未能确定目标列：{hint}，无法作为目标列。请检查数据是否加载正确"
    return last, None


def _action_split(params: Dict[str, Any], manager: ConversationManager) -> Tuple[str, None]:
    if manager.current_data is None:
        return "\n\n❌ 还没有加载数据集。", None

    df = manager.current_data
    test_size = float(params.get("test_size", 0.2))
    random_state = int(params.get("random_state", 42))

    target_col, err = _resolve_target_column(df, params.get("target"))
    if target_col is None:
        return f"\n\n❌ 数据分割失败：{err}", None

    # 同族列（如 target 与 target_label）必须一起排除，否则标签泄漏
    leak_cols = [c for c in _label_family_columns(df, target_col) if c != target_col]
    X = df.drop(columns=[target_col] + leak_cols)
    y = df[target_col]

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
    manager.current_target_col = target_col

    text = (
        "\n\n---\n\n**✓ 数据分割完成**\n\n"
        f"- **训练集大小**: {X_train.shape[0]} 样本\n"
        f"- **测试集大小**: {X_test.shape[0]} 样本\n"
        f"- **特征数**: {X_train.shape[1]}\n"
        f"- **测试集比例**: {test_size * 100:.0f}%\n"
        f"- **目标列**: {target_col}\n"
    )
    if leak_cols:
        text += f"- **已排除同源列**: {', '.join(leak_cols)}（与目标列同义，避免标签泄漏）\n"
    if obj_cols:
        text += f"- **已自动编码的非数值列**: {', '.join(obj_cols)}\n"

    y_nan = int(y.isna().sum())
    x_nan = int(X.isna().sum().sum())
    if y_nan or x_nan:
        text += (
            f"\n> ⚠ 数据中仍有缺失值（特征 {x_nan} 个 / 目标 {y_nan} 个），"
            "直接训练会失败，建议先执行 fill_missing。\n"
        )
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

    if manager.current_data is None:
        return "\n\n❌ 还没有加载数据集，请先执行 load。", None

    # 老师（或模型）显式指定了目标列：若与当前分割不一致，重新按该列分割。
    # 旧版完全忽略 target 参数，导致模型说"改用正确的目标列重新训练"却毫无效果。
    requested_target = params.get("target")
    if requested_target and str(requested_target) != manager.current_target_col:
        appendix, _ = _action_split({"target": requested_target}, manager)
        if "✓" not in appendix:
            return appendix or "\n\n❌ 按指定目标列重新分割失败。", None

    if not _ensure_split(manager):
        return "\n\n❌ 没有可用的训练数据，且自动分割失败。", None

    # ---- 训练前校验：缺失值会让 sklearn 抛出难懂的异常，这里提前拦截并给出可执行的建议 ----
    x_nan = int(manager.X_train.isna().sum().sum())
    y_nan = int(manager.y_train.isna().sum())
    if y_nan or x_nan:
        return (
            f"\n\n❌ 训练失败：训练数据中仍有缺失值（特征 {x_nan} 个 / 目标 {y_nan} 个）。"
            f"当前目标列：{manager.current_target_col}。"
            "请先执行 fill_missing 补齐缺失值，或检查目标列是否选择正确。"
        ), None

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
        # clone: MODEL_REGISTRY 里是共享的单例，直接 fit 会让会话之间互相覆盖模型状态
        model = clone(available[model_key])
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
        f"- **目标列**: {manager.current_target_col}\n"
        f"- **训练样本数**: {manager.X_train.shape[0]}\n"
        f"- **特征数**: {manager.X_train.shape[1]}\n"
    )
    if train_acc is not None:
        text += f"- **训练集准确率**: {train_acc:.4f}\n"
    text += "\n接下来可以对模型执行 evaluate 操作，查看测试集表现。"

    # 结构化训练信息：前端据此把同一条指令里的多次训练合并成一张紧凑卡片
    train_extra: Dict[str, Any] = {
        "train": {
            "model": MODEL_LABELS.get(model_key, model_key),
            "model_key": model_key,
            "task_type": task_type,
            "samples": int(manager.X_train.shape[0]),
            "features": int(manager.X_train.shape[1]),
        }
    }
    if train_acc is not None:
        train_extra["train"]["train_acc"] = round(float(train_acc), 4)
    return text, None, train_extra


def _action_evaluate(params: Dict[str, Any], manager: ConversationManager) -> Tuple[str, Optional[Dict[str, Any]], Dict[str, Any]]:
    if manager.current_model is None:
        return "\n\n❌ 还没有训练模型，请先执行 train 操作。", None, {}

    y_pred = manager.current_model.predict(manager.X_test)
    manager.last_eval_true = manager.y_test.to_numpy()
    manager.last_eval_pred = y_pred

    task_type = manager.current_task_type
    model_label = MODEL_LABELS.get(manager.current_model_name, manager.current_model_name)
    text = f"\n\n---\n\n**✓ 模型评估结果（{model_label}）**\n\n"
    metrics: List[Dict[str, Any]] = []
    chart: Optional[Dict[str, Any]] = None

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
        metrics.append({
            "label": "测试集准确率",
            "value": f"{acc * 100:.2f}%",
            "hint": f"原始值 {acc:.4f} · 越高越好",
        })
        try:
            cm = confusion_matrix(manager.y_test, y_pred)
            cm_df = pd.DataFrame(cm)
            text += f"\n**混淆矩阵**（行=真实值，列=预测值）：\n\n{cm_df.to_markdown()}\n"

            raw_labels = list(pd.unique(manager.y_test))
            labels = _class_labels(manager, raw_labels)
            data = [
                [i, j, int(cm[i][j])]
                for i in range(len(labels)) for j in range(len(labels))
            ]
            total = int(cm.sum()) or 1
            correct = int(sum(cm[i][i] for i in range(len(labels))))
            metrics.append({
                "label": "样本数",
                "value": str(total),
                "hint": f"测试集 · 预测正确 {correct} 个",
            })
            chart = {
                "type": "heatmap",
                "title": f"混淆矩阵（{model_label}）",
                "xLabel": "预测值",
                "yLabel": "真实值",
                "xLabels": labels,
                "yLabels": labels,
                "min": 0,
                "max": int(cm.max()) if cm.size else 1,
                "series": [{"name": "样本数", "data": data}],
            }
        except Exception:
            logger.exception("Failed to build confusion matrix chart")
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
        metrics += [
            {"label": "R²", "value": f"{r2:.4f}", "hint": "越接近 1 越好"},
            {"label": "RMSE", "value": f"{rmse:.4f}", "hint": "平均预测偏差，越小越好"},
            {"label": "MSE", "value": f"{mse:.4f}", "hint": "均方误差"},
        ]

    if len(manager.metric_history) > 1:
        text += "\n**历史模型指标对比：**\n\n"
        history_df = pd.DataFrame(manager.metric_history).T
        text += history_df.to_markdown()
        text += "\n"
    # model/model_key：前端据此把多次 evaluate 聚合成一张跨模型对比表
    return text, chart, {
        "metrics": metrics,
        "task_type": task_type,
        "model": model_label,
        "model_key": manager.current_model_name,
    }


def _action_plot(params: Dict[str, Any], manager: ConversationManager) -> Tuple[str, Optional[Dict[str, Any]]]:
    chart_payload = charts.create_chart(params, manager)
    if chart_payload:
        return "", chart_payload
    return "\n\n❌ 无法生成图表，请确认已加载数据且指定了有效的列。", None
