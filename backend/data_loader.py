"""
Data loading utilities for sklearn built-in datasets and DOT graph files.
"""
from pathlib import Path
from typing import Tuple

import pandas as pd
from sklearn import datasets
import pydot


SKLEARN_LOADERS = {
    "iris": datasets.load_iris,
    "wine": datasets.load_wine,
    "breast_cancer": datasets.load_breast_cancer,
    "california_housing": datasets.fetch_california_housing,
}


def load_sklearn_dataset(name: str) -> Tuple[pd.DataFrame, str]:
    """
    Load a built-in sklearn dataset into a DataFrame and return (df, description).
    """
    key = name.lower()
    if key not in SKLEARN_LOADERS:
        raise ValueError(f"Unsupported dataset '{name}'.")

    loader = SKLEARN_LOADERS[key]
    dataset = loader()

    feature_names = getattr(dataset, "feature_names", None)
    if feature_names is None:
        feature_names = [f"feature_{i}" for i in range(dataset.data.shape[1])]

    df = pd.DataFrame(dataset.data, columns=feature_names)

    target = getattr(dataset, "target", None)
    if target is not None:
        df["target"] = target
        target_names = getattr(dataset, "target_names", None)
        # 只为「类别索引型」目标生成 target_label：
        # 分类数据集（iris/wine/breast_cancer）的 target 是 0..n-1 的整数，可映射到名称；
        # 回归数据集（california_housing）的 target 是连续浮点值，target_names 只有
        # ['MedHouseVal'] 一项，强行映射会把整列变成 NaN —— 这正是旧版把全 NaN 目标列
        # 喂给 split/train 的根源。
        if (
            target_names is not None
            and pd.api.types.is_integer_dtype(df["target"])
            and len(df) > 0
            and int(df["target"].max()) < len(target_names)
        ):
            mapping = {i: name for i, name in enumerate(target_names)}
            df["target_label"] = df["target"].map(mapping)

    descr = getattr(dataset, "DESCR", "")
    return df, descr


def load_dot_dataset(path: str) -> Tuple[pd.DataFrame, str]:
    """
    Load a DOT graph file and return an edge list DataFrame and a short description.
    """
    dot_path = Path(path)
    if not dot_path.exists():
        raise FileNotFoundError(f"DOT file not found: {dot_path}")

    graphs = pydot.graph_from_dot_file(str(dot_path))
    if not graphs:
        raise ValueError(f"Failed to parse DOT file: {dot_path}")

    graph = graphs[0]
    edges = graph.get_edges()
    edge_rows = []
    for edge in edges:
        edge_rows.append(
            {
                "source": edge.get_source(),
                "target": edge.get_destination(),
                "label": edge.get_label() or "",
            }
        )

    if not edge_rows:
        edge_rows.append({"source": None, "target": None, "label": None})

    df = pd.DataFrame(edge_rows)
    descr = (
        f"DOT graph from {dot_path.name} with "
        f"{len(graph.get_nodes())} nodes and {len(edges)} edges."
    )
    return df, descr
