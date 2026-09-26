"""
ECharts payload builders driven by LLM-provided action parameters.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

from backend.state import ConversationManager

logger = logging.getLogger(__name__)


def create_chart(action_params: Dict[str, Any], manager: ConversationManager) -> Optional[Dict[str, Any]]:
    """Create an ECharts configuration from LLM action parameters."""
    if not action_params or manager.current_data is None:
        return None

    chart_type = action_params.get("chart_type", "line")

    builders = {
        "scatter": build_scatter,
        "histogram": build_histogram,
        "line": build_line,
        "bar": build_bar,
        # TASK-206: new chart types
        "boxplot": build_boxplot,
        "heatmap": build_heatmap,
        "correlation_matrix": build_heatmap,
    }
    builder = builders.get(chart_type)
    if builder is None:
        logger.warning("Unsupported chart_type=%s", chart_type)
        return None
    return builder(action_params, manager)


def build_scatter(params: Dict[str, Any], manager: ConversationManager) -> Optional[Dict[str, Any]]:
    df = manager.current_data
    x_col = params.get("x_column")
    y_col = params.get("y_column")

    if not x_col or not y_col or x_col not in df.columns or y_col not in df.columns:
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        if len(numeric_cols) >= 2:
            x_col, y_col = numeric_cols[0], numeric_cols[1]
        else:
            return None

    x = df[x_col].to_numpy()
    y = df[y_col].to_numpy()

    return {
        "type": "scatter",
        "title": f"{y_col} vs {x_col}",
        "xLabel": x_col,
        "yLabel": y_col,
        "series": [{
            "name": f"{y_col} vs {x_col}",
            "points": list(map(list, zip(x, y))),
        }],
    }


def build_histogram(params: Dict[str, Any], manager: ConversationManager) -> Optional[Dict[str, Any]]:
    df = manager.current_data
    column = params.get("column")

    if not column or column not in df.columns:
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        if numeric_cols:
            column = numeric_cols[0]
        else:
            return None

    bins = params.get("bins", 20)
    data = df[column].dropna().to_numpy()
    counts, edges = np.histogram(data, bins=bins)
    centers = 0.5 * (edges[1:] + edges[:-1])

    return {
        "type": "bar",
        "chartSubtype": "histogram",
        "title": f"{column} 分布（直方图）",
        "xLabel": column,
        "yLabel": "频数",
        "series": [
            {
                "name": column,
                "x": centers.tolist(),
                "y": counts.tolist(),
            }
        ],
    }


def build_line(params: Dict[str, Any], manager: ConversationManager) -> Optional[Dict[str, Any]]:
    df = manager.current_data
    if df is None:
        logger.warning("No data loaded, cannot build line chart")
        return None

    columns = params.get("columns", [])

    matched_columns = []
    if columns:
        for col in columns:
            if col in df.columns:
                matched_columns.append(col)
            else:
                col_lower = col.lower()
                for df_col in df.columns:
                    if col_lower in df_col.lower() or df_col.lower() in col_lower:
                        matched_columns.append(df_col)
                        break

    if not matched_columns:
        numeric_cols = df.select_dtypes(include=["number"]).columns.tolist()
        matched_columns = [c for c in numeric_cols if "target" not in c.lower()][:6]

    if not matched_columns:
        logger.warning("No valid columns found for line chart")
        return None

    logger.info("Building line chart with columns: %s", matched_columns)

    series = []
    x_vals = list(range(len(df)))
    for col in matched_columns:
        if col in df.columns:
            series.append({"name": col, "x": x_vals, "y": df[col].tolist()})

    if not series:
        logger.warning("No series data generated for line chart")
        return None

    return {
        "type": "line",
        "title": params.get("title", "数据趋势图"),
        "xLabel": "样本索引",
        "yLabel": "数值",
        "series": series,
    }


_AGG_LABELS = {"mean": "均值", "median": "中位数", "max": "最大值", "min": "最小值", "sum": "总和"}


def _match_columns(df: pd.DataFrame, columns: Any, numeric_only: bool = True) -> List[str]:
    """按名称精确/模糊匹配列（大小写不敏感、支持包含关系），去重保序。"""
    matched: List[str] = []
    for col in columns or []:
        name = str(col)
        if name in df.columns:
            hit = name
        else:
            low = name.lower()
            hit = next(
                (
                    c for c in df.columns
                    if low in str(c).lower() or str(c).lower() in low
                ),
                None,
            )
        if hit and hit not in matched:
            matched.append(hit)
    if numeric_only:
        matched = [c for c in matched if pd.api.types.is_numeric_dtype(df[c])]
    return matched


def build_bar(params: Dict[str, Any], manager: ConversationManager) -> Optional[Dict[str, Any]]:
    df = manager.current_data

    # 聚合模式：{"chart_type": "bar", "agg": "mean", "columns": [...]}
    # 每列聚合出一个值画一根柱子，用于"对比同量级特征的均值"这类需求。
    # 旧版 bar 只支持 x_column/y_column 画原始行，画不出列级聚合，
    # 模型无奈之下只能编造"已生成"的假图表。
    agg = str(params.get("agg") or "").lower()
    if agg in _AGG_LABELS:
        return _build_agg_bar(params, manager, agg)

    x_col = params.get("x_column")
    y_col = params.get("y_column")

    if not x_col or not y_col or x_col not in df.columns or y_col not in df.columns:
        return None

    x_data = df[x_col].astype(str).tolist()
    y_data = df[y_col].tolist()

    return {
        "type": "bar",
        "title": params.get("title", f"{y_col} by {x_col}"),
        "xLabel": x_col,
        "yLabel": y_col,
        "series": [
            {
                "name": y_col,
                "x": x_data,
                "y": y_data,
            }
        ],
    }


def _build_agg_bar(params: Dict[str, Any], manager: ConversationManager, agg: str) -> Optional[Dict[str, Any]]:
    """各列聚合值对比柱状图（agg ∈ mean/median/max/min/sum）。"""
    df = manager.current_data
    matched = _match_columns(df, params.get("columns"))
    if not matched:
        # 未指定列：取全部数值特征列（排除目标列），最多 12 根柱子
        matched = [
            c for c in df.select_dtypes(include=["number"]).columns
            if "target" not in str(c).lower()
        ]
    matched = matched[: int(params.get("max_columns", 12))]
    if not matched:
        return None

    values = df[matched].agg(agg)
    unit = _AGG_LABELS[agg]
    return {
        "type": "bar",
        "chartSubtype": "agg-bar",
        "title": params.get("title") or f"各特征{unit}对比",
        "xLabel": "特征",
        "yLabel": unit,
        "series": [{
            "name": unit,
            "x": matched,
            "y": [round(float(v), 4) for v in values.tolist()],
        }],
    }


def build_boxplot(params: Dict[str, Any], manager: ConversationManager) -> Optional[Dict[str, Any]]:
    """Boxplot over one or more numeric columns (TASK-206)."""
    df = manager.current_data
    columns = params.get("columns", [])

    if columns:
        matched = [c for c in columns if c in df.columns and pd.api.types.is_numeric_dtype(df[c])]
    else:
        matched = df.select_dtypes(include=["number"]).columns.tolist()[:6]

    if not matched:
        return None

    series = []
    for col in matched:
        vals = df[col].dropna()
        if vals.empty:
            continue
        q1, q2, q3 = vals.quantile([0.25, 0.5, 0.75])
        iqr = q3 - q1
        low_fence = vals[vals >= q1 - 1.5 * iqr].min()
        high_fence = vals[vals <= q3 + 1.5 * iqr].max()
        outliers = vals[(vals < low_fence) | (vals > high_fence)].tolist()
        series.append({
            "name": col,
            "box": [float(low_fence), float(q1), float(q2), float(q3), float(high_fence)],
            "outliers": [float(o) for o in outliers[:50]],
        })

    if not series:
        return None

    return {
        "type": "boxplot",
        "title": params.get("title", "箱线图"),
        "xLabel": "特征",
        "yLabel": "数值",
        "series": series,
    }


def build_heatmap(params: Dict[str, Any], manager: ConversationManager) -> Optional[Dict[str, Any]]:
    """Correlation heatmap over numeric columns (TASK-206)."""
    df = manager.current_data
    numeric_df = df.select_dtypes(include=["number"])
    if numeric_df.shape[1] < 2:
        return None

    max_cols = int(params.get("max_columns", 10))
    corr = numeric_df.corr(numeric_only=True).round(3)
    if corr.shape[1] > max_cols:
        corr = corr.iloc[:max_cols, :max_cols]

    cols = corr.columns.tolist()
    data = [
        [i, j, float(corr.iloc[i, j])]
        for i in range(len(cols))
        for j in range(len(cols))
    ]

    return {
        "type": "heatmap",
        "title": params.get("title", "相关性矩阵热力图"),
        "xLabel": "特征",
        "yLabel": "特征",
        "xLabels": cols,
        "yLabels": cols,
        "min": -1.0,
        "max": 1.0,
        "series": [{"name": "相关系数", "data": data}],
    }
