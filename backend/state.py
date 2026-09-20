"""
Conversation state management for each teaching session.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class ConversationManager:
    """
    Stores dialogue history and the currently loaded dataset / model state.
    """

    def __init__(self, session_id: str = "") -> None:
        self.session_id = session_id
        self.title: str = ""  # TASK-201: auto-generated session title
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

    # ------------------------------------------------------------------ history

    def add_message(self, role: str, content: str) -> None:
        self.history.append({"role": role, "content": content})
        logger.debug("Message added role=%s content_preview=%s", role, content[:200])

    def get_history(self) -> List[Dict[str, str]]:
        return list(self.history)

    # ------------------------------------------------------------------ data

    def set_data(self, df: pd.DataFrame, name: str) -> None:
        self.current_data = df
        self.current_dataset_name = name
        if name in ("iris", "wine", "breast_cancer"):
            self.current_task_type = "classification"
        elif name == "california_housing":
            self.current_task_type = "regression"
        logger.info("Dataset set name=%s shape=%s task=%s", name, df.shape, self.current_task_type)

    def set_uploaded_data(self, df: pd.DataFrame, filename: str) -> None:
        """Set uploaded CSV data and infer the task type."""
        self.current_data = df
        self.current_dataset_name = filename
        if df.shape[1] > 0:
            last_col = df.iloc[:, -1]
            if last_col.dtype in ("object", "category") or last_col.nunique() <= 10:
                self.current_task_type = "classification"
            else:
                self.current_task_type = "regression"
        logger.info(
            "Uploaded dataset set name=%s shape=%s task=%s",
            filename, df.shape, self.current_task_type,
        )

    def get_data(self) -> Tuple[Optional[pd.DataFrame], Optional[str]]:
        return self.current_data, self.current_dataset_name

    # ------------------------------------------------------------------ persistence support

    def snapshot(self) -> Dict[str, Any]:
        """Serialize the persistable part of the session (history + dataset metadata).

        Note: DataFrames / fitted models are not persisted; only dialogue history
        and dataset name survive a server restart.
        """
        return {
            "session_id": self.session_id,
            "title": self.title,
            "history": list(self.history),
            "dataset_name": self.current_dataset_name,
            "task_type": self.current_task_type,
        }

    def restore(self, state: Dict[str, Any]) -> None:
        """Restore the persistable part of the session."""
        self.session_id = state.get("session_id", self.session_id)
        self.title = state.get("title", "") or ""
        self.history = list(state.get("history", []))
        self.current_dataset_name = state.get("dataset_name")
        self.current_task_type = state.get("task_type")

    # ------------------------------------------------------------------ cleanup

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
