"""
LLM 输出质量回归集（P1-3）。

把历史上真实踩过的 LLM 输出形态与数据状态事故固化为用例：
改提示词 / 改解析器 / 改状态管理后跑一遍，防止旧问题复发。

零依赖：既可用 pytest，也可直接运行（无需安装 pytest）：
    python tests/test_llm_output_regression.py
    python -m pytest tests/ -q      # 若已安装 pytest
"""
from __future__ import annotations

import asyncio
import json
import sys
import traceback
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.agent as agent  # noqa: E402
from backend import actions  # noqa: E402
from backend.data_loader import load_sklearn_dataset  # noqa: E402
from backend.llm_client import parse_json_response  # noqa: E402
from backend.state import ConversationManager  # noqa: E402


# ======================================================================
# 一、JSON 解析层：LLM 真实返回的各种「脏」形态
# ======================================================================

def test_direct_json():
    data, cleaned = parse_json_response('{"reply": "好的老师"}')
    assert data == {"reply": "好的老师"}
    assert cleaned == ""


def test_json_in_fenced_block():
    raw = '先说明一下\n```json\n{"reply": "已加载"}\n```\n结束'
    data, cleaned = parse_json_response(raw)
    assert data == {"reply": "已加载"}
    assert "先说明一下" in cleaned and "结束" in cleaned


def test_json_in_unlabelled_fence():
    raw = '```\n{"action": "load", "params": {"dataset": "iris"}}\n```'
    data, _ = parse_json_response(raw)
    assert data and data["action"] == "load"


def test_prose_then_bare_json_incident():
    """事故 A：模型返回开场白 + 裸 JSON（无代码块），旧版当纯文本导致循环静默退出。"""
    raw = (
        "好的老师，正在用随机森林训练模型：\n"
        '{"action": "train", "params": {"model": "random_forest"}, "reply": "好的老师，正在用随机森林训练模型："}'
    )
    data, cleaned = parse_json_response(raw)
    assert data is not None, "散文 + 裸 JSON 必须能解析"
    assert data["action"] == "train"
    assert data["params"]["model"] == "random_forest"
    assert "正在用随机森林训练模型" in cleaned


def test_bare_json_with_nested_object():
    raw = '思考如下：\n{"action": "plot", "params": {"chart_type": "bar", "options": {"stack": true}}}'
    data, _ = parse_json_response(raw)
    assert data["params"]["options"] == {"stack": True}


def test_braces_inside_json_string():
    """字符串里的花括号不能干扰括号配平扫描。"""
    raw = '说明：{"reply": "用 {a: 1} 这种写法表示字典"}'
    data, _ = parse_json_response(raw)
    assert data == {"reply": "用 {a: 1} 这种写法表示字典"}


def test_first_valid_object_wins():
    raw = '{"action": "load"}\n另外 {"action": "train"}'
    data, _ = parse_json_response(raw)
    assert data["action"] == "load"


def test_decoy_invalid_object_is_skipped():
    raw = '模板形如 {name: 值} 不合法\n{"action": "preview", "params": {"rows": 5}}'
    data, _ = parse_json_response(raw)
    assert data["action"] == "preview"


def test_plain_text_returns_none():
    raw = "什么是过拟合？简单说就是模型把训练数据背下来了。"
    data, cleaned = parse_json_response(raw)
    assert data is None
    assert cleaned == raw


# ======================================================================
# 二、动作归一化：模型输出的各种 actions 变体
# ======================================================================

def test_single_action_shape():
    got = agent._extract_actions({"action": "load", "params": {"dataset": "iris"}})
    assert got == [{"action": "load", "params": {"dataset": "iris"}}]


def test_actions_dict_array():
    got = agent._extract_actions({
        "actions": [
            {"action": "check_missing", "params": {}},
            {"action": "fill_missing", "params": {"method": "median"}},
        ]
    })
    assert [a["action"] for a in got] == ["check_missing", "fill_missing"]


def test_actions_bare_string_array():
    """事故：模型把 actions 写成纯字符串数组。"""
    got = agent._extract_actions({"actions": ["split", "train"]})
    assert got == [{"action": "split", "params": {}}, {"action": "train", "params": {}}]


def test_actions_alias_keys():
    """事故：模型用 name / type 代替 action 键。"""
    got = agent._extract_actions({"actions": [{"name": "evaluate"}, {"type": "plot", "params": {"chart_type": "bar"}}]})
    assert [a["action"] for a in got] == ["evaluate", "plot"]
    assert got[1]["params"] == {"chart_type": "bar"}


def test_actions_truncated_to_max_steps():
    many = [{"action": "preview", "params": {"rows": i}} for i in range(1, 12)]
    got = agent._extract_actions({"actions": many})
    assert len(got) == 5, "单条指令最多执行 5 步"


def test_actions_ignores_junk_items():
    got = agent._extract_actions({"actions": [None, "", {"foo": "bar"}, "load"]})
    assert got == [{"action": "load", "params": {}}]


# ======================================================================
# 三、过渡语检测与纠偏 / 重试熔断（用桩替换 LLM，不打真实 API）
# ======================================================================

def test_operation_keyword_detection():
    cases = [
        ("用随机森林训练模型并评估效果", True),
        ("画出特征分布图", True),
        ("加载 iris 数据集", True),
        ("check the missing values", True),
        ("什么是过拟合？", False),
        ("解释一下决策树的原理", False),
    ]
    for command, expected in cases:
        got = bool(agent._OPERATION_KEYWORD_RE.search(command))
        assert got is expected, f"{command!r} 期望 {expected}，实际 {got}"


def _run_with_stub(manager, command, responses):
    """用固定回复序列替换真实 LLM，驱动一次完整的 agent 循环。"""
    calls = {"n": 0, "messages": []}

    async def fake_invoke(api_key, messages, model_name=None):
        idx = min(calls["n"], len(responses) - 1)
        calls["n"] += 1
        calls["messages"].append(messages)
        return responses[idx]

    original = agent.invoke_deepseek
    agent.invoke_deepseek = fake_invoke
    try:
        result = asyncio.run(
            # 注意签名顺序：command 在前，api_key 在后
            agent.process_user_command(command, manager, "dummy", level_prompt="", student_level="intermediate")
        )
    finally:
        agent.invoke_deepseek = original
    return result, calls


def test_transition_only_reply_triggers_corrective_retry():
    """事故 A：第一轮只有过渡语（无 action），应注入纠偏提示并重试，而不是空转结束。"""
    manager = ConversationManager("t-transition")
    manager.set_data(load_sklearn_dataset("iris")[0], "iris")

    plan = [
        '{"reply": "好的老师，正在用随机森林训练模型："}',  # 纯过渡语，无动作
        json.dumps({"actions": [{"action": "train", "params": {"model": "random_forest"}}], "reply": "开始训练："}, ensure_ascii=False),
        '{"reply": "训练完成，随时可以评估。"}',  # 收尾总结
    ]
    result, calls = _run_with_stub(manager, "用随机森林训练模型并评估效果", plan)

    assert calls["n"] == 3, f"应为 纠偏 → 执行 → 总结 三轮，实际 {calls['n']} 轮"
    nudged = any(
        "系统纠偏" in (m.get("content") or "")
        for messages in calls["messages"] for m in messages
    )
    assert nudged, "第二轮必须带上纠偏提示"
    assert result["steps"] == ["train"], "纠偏后必须真正执行动作"
    assert "✓" in result["results"][0]["text"]
    assert "训练完成" in result["reply"]


def test_retry_cap_stops_endless_failure():
    """事故：同一动作连续失败被无限重试（曾空转 18 步）。达到上限必须停止并给出诊断。"""
    manager = ConversationManager("t-retrycap")
    manager.set_data(load_sklearn_dataset("california_housing")[0], "california_housing")

    failing = json.dumps(
        {"action": "train", "params": {"model": "random_forest", "target": "target_label"}, "reply": "开始训练："},
        ensure_ascii=False,
    )
    result, calls = _run_with_stub(manager, "用随机森林训练并评估效果", [failing])

    assert calls["n"] <= 3, "同一动作失败达上限后不应继续调用 LLM"
    assert result["steps"] == ["train", "train"], "只允许重试 2 次"
    assert len(result["results"]) == 3
    assert "停止重试" in result["results"][-1]["text"]
    assert "排查" in result["reply"] or "建议" in result["reply"], "应给出可执行的排查建议"


# ======================================================================
# 四、跨数据集状态隔离与目标列解析（2026-09-23 事故）
# ======================================================================

def test_regression_dataset_has_no_phantom_label_column():
    """事故：california_housing 被造出整列 NaN 的 target_label，被当成目标列。"""
    df, _ = load_sklearn_dataset("california_housing")
    assert "target_label" not in df.columns
    assert "target" in df.columns


def test_classification_dataset_keeps_label_column():
    for name in ("iris", "wine", "breast_cancer"):
        df, _ = load_sklearn_dataset(name)
        assert "target_label" in df.columns
        assert not df["target_label"].isna().all()


def test_switching_dataset_clears_derived_state():
    """事故：切数据集后 train 复用了上一个数据集的 X_train（KNN 报 120 样本实为 iris）。"""
    manager = ConversationManager("t-switch")
    manager.set_data(load_sklearn_dataset("iris")[0], "iris")
    actions.execute_action("split", {}, manager)
    actions.execute_action("train", {"model": "knn"}, manager)
    assert manager.X_train is not None

    manager.set_data(load_sklearn_dataset("california_housing")[0], "california_housing")
    assert manager.X_train is None and manager.y_train is None
    assert manager.current_model is None
    assert manager.current_target_col is None


def test_split_after_switch_uses_new_dataset():
    manager = ConversationManager("t-switch2")
    manager.set_data(load_sklearn_dataset("iris")[0], "iris")
    actions.execute_action("split", {}, manager)
    manager.set_data(load_sklearn_dataset("california_housing")[0], "california_housing")
    text, _, _ = actions.execute_action("train", {"model": "random_forest"}, manager)
    assert "16512" in text, "必须用新数据集的训练集（20640 × 0.8）"
    assert "target" in text


def test_split_rejects_all_nan_target():
    manager = ConversationManager("t-nantarget")
    manager.set_data(pd.DataFrame({"a": [1.0, 2.0, 3.0], "target": [None, None, None]}), "manual")
    text, _, _ = actions.execute_action("split", {}, manager)
    assert "❌" in text and "整列都是缺失值" in text


def test_split_rejects_unknown_explicit_target():
    manager = ConversationManager("t-unknown")
    manager.set_data(load_sklearn_dataset("california_housing")[0], "california_housing")
    text, _, _ = actions.execute_action("split", {"target": "target_label"}, manager)
    assert "❌" in text
    assert "可用目标列：target" in text, "报错时须给出可用候选列"


def test_split_excludes_label_leak_columns():
    """隐藏事故：iris 的 target 与 target_label 互为特征，模型在抄答案。"""
    manager = ConversationManager("t-leak")
    manager.set_data(load_sklearn_dataset("iris")[0], "iris")
    text, _, _ = actions.execute_action("split", {}, manager)
    assert "已排除同源列" in text
    assert manager.X_train.shape[1] == 4, "iris 只有 4 个真实特征"


def test_train_reports_missing_values_instead_of_crashing():
    manager = ConversationManager("t-nan")
    manager.set_data(
        pd.DataFrame({"a": [1.0] + [None] * 4 + [6.0, 7.0, 8.0, 9.0, 10.0], "target": [0, 1, 0, 1, 0, 1, 0, 1, 0, 1]}),
        "manual",
    )
    text, _, _ = actions.execute_action("train", {"model": "random_forest"}, manager)
    assert "❌" in text and "fill_missing" in text


# ======================================================================
# 五、fill_missing 不许假成功 / evaluate 结构化指标（P1-1）
# ======================================================================

def test_fill_missing_never_reports_fake_success():
    manager = ConversationManager("t-fill")
    df = pd.DataFrame({"only_nan": [None, None, None], "target": [0, 1, 0]})
    manager.set_data(df, "manual")
    manager.current_target_col = "target"
    text, _, _ = actions.execute_action("fill_missing", {"method": "median"}, manager)
    assert "❌" in text, "缺失数未下降必须报失败"
    assert "填充失败" in text


def test_fill_missing_skips_target_column():
    manager = ConversationManager("t-fill2")
    df = pd.DataFrame({"a": [1.0, None, 3.0], "target": [0, None, 0]})
    manager.set_data(df, "manual")
    manager.current_target_col = "target"
    text, _, _ = actions.execute_action("fill_missing", {"method": "median"}, manager)
    assert "已跳过目标列" in text
    assert df["target"].isna().sum() == 1, "目标列不得被中位数污染"


def test_evaluate_returns_metric_cards():
    manager = ConversationManager("t-eval")
    manager.set_data(load_sklearn_dataset("iris")[0], "iris")
    actions.execute_action("split", {}, manager)
    actions.execute_action("train", {"model": "random_forest"}, manager)
    text, chart, extra = actions.execute_action("evaluate", {}, manager)

    assert extra["task_type"] == "classification"
    labels = [m["label"] for m in extra["metrics"]]
    assert "测试集准确率" in labels
    assert chart and chart["type"] == "heatmap", "混淆矩阵应产出热力图"
    assert len(chart["xLabels"]) >= 2
    assert "准确率" in text  # markdown 兜底仍在


def test_execute_action_always_returns_three_items():
    manager = ConversationManager("t-shape")
    manager.set_data(load_sklearn_dataset("iris")[0], "iris")
    for action, params in [("load", {"dataset": "iris"}), ("preview", {}), ("未知", {})]:
        out = actions.execute_action(action, params, manager)
        assert len(out) == 3, f"{action} 必须返回 (text, chart, extra)"


# ======================================================================
# 零依赖运行器（无 pytest 时直接 python tests/test_llm_output_regression.py）
# ======================================================================

def _run_all() -> int:
    tests = [
        (name, fn) for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    passed, failed = 0, []
    for name, fn in tests:
        try:
            fn()
            passed += 1
            print(f"  ✓ {name}")
        except Exception as exc:  # noqa: BLE001
            failed.append((name, exc))
            print(f"  ✗ {name}: {exc}")
    print(f"\n{passed}/{len(tests)} 通过")
    if failed:
        print("\n失败详情：")
        for name, exc in failed:
            print(f"\n[{name}] {exc}")
            traceback.print_exception(type(exc), exc, exc.__traceback__)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(_run_all())
