"""运营官 prepare_brief 评测运行器（code grader，确定性判定）。

- 数据集：桥接投影形状（input/materials/expect），mock 可全跑；live 需显式开启。
- 判定分级：核心不变量两档同查（status/requirements/route/material_ids/段落范围）；
  `mock_exact`（逐字冻结字段）只在 mock 档判定——live 档这些是推断字段，由
  confirm 闸门人工确认，不作 exact 判分。
- 每个 live case = 恰好一次模型调用（needs_input 零调用），无自动重试；
  `max_calls` 硬上限，超出部分标 skipped。
- 输出恒带 mock/真实标记，`predicts_real_traffic` 恒为 false。
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from backend.adapters.orch_bridge import OperatorTeamAdapter, orchestration_ref_digest


def load_dataset(path: Path | str) -> dict:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if document.get("schema") != "operator-eval.dataset.v1":
        raise ValueError("unsupported dataset schema")
    return document


def _rows_and_refs(case: dict) -> tuple[list[dict], list[dict]]:
    rows, refs = [], []
    for i, m in enumerate(case.get("materials", [])):
        text = m.get("text")
        if text is None:
            text = m["text_unit"] * int(m.get("repeat", 1))
        mid = m.get("id") or f"mat{i + 1}"
        rows.append({"id": mid, "text": text, "kind": m.get("kind"),
                     "label": m.get("label") or mid, "source_url": m.get("source_url")})
        refs.append({"id": mid, "sha256": orchestration_ref_digest(text)})
    return rows, refs


def _make_call(case: dict) -> SimpleNamespace:
    rows, refs = _rows_and_refs(case)
    payload = {"user_input": case["input"]["user_input"],
               "input_mode": case["input"].get("input_mode", "idea"),
               "material_refs": refs,
               "selected_opportunity_ref": None}
    if case["input"].get("requirements") is not None:
        payload["requirements"] = case["input"]["requirements"]
    if case["input"].get("edit_scope") is not None:
        payload["edit_scope"] = case["input"]["edit_scope"]
    call = SimpleNamespace(request_id=f"req_{case['id']}", agent_id="operations_officer",
                           action="prepare_brief", contract_version="seven-agent.v0.1",
                           input=payload, context=SimpleNamespace(account_id="eval_account"))
    return call, rows


def _check(expect: dict, result: dict, *, mode: str) -> list[str]:
    failures = []
    data = result.get("data") or {}
    if "status" in expect:
        wanted = expect["status"] if isinstance(expect["status"], list) else [expect["status"]]
        if result.get("status") not in wanted:
            failures.append(f"status: want {wanted} got {result.get('status')}")
    if expect.get("questions_nonempty") and not result.get("questions"):
        failures.append("needs_input must carry questions")
    # 数据级断言只对 ok 结果判定；needs_input/error 不承载 Brief 数据
    if result.get("status") != "ok":
        return failures
    if "requirements" in expect:
        want = {r["id"]: r["text"] for r in expect["requirements"]}
        got = {r["id"]: r["text"] for r in data.get("requirements") or []}
        if got != want:
            failures.append(f"requirements: want {want} got {got}")
    if "route" in expect and data.get("route") != expect["route"]:
        failures.append(f"route: want {expect['route']} got {data.get('route')}")
    if "material_ids" in expect and data.get("material_ids") != expect["material_ids"]:
        failures.append(f"material_ids: want {expect['material_ids']} got {data.get('material_ids')}")
    scope = data.get("edit_scope") or {}
    if "target_segment_ids" in expect and scope.get("target_segment_ids") != expect["target_segment_ids"]:
        failures.append(f"target_segment_ids: want {expect['target_segment_ids']} got {scope.get('target_segment_ids')}")
    if "preserve_segment_ids" in expect and scope.get("preserve_segment_ids") != expect["preserve_segment_ids"]:
        failures.append(f"preserve_segment_ids: want {expect['preserve_segment_ids']} got {scope.get('preserve_segment_ids')}")
    if mode == "mock":
        for key, want in (expect.get("mock_exact") or {}).items():
            if data.get(key) != want:
                failures.append(f"{key} (mock_exact): want {want!r} got {data.get(key)!r}")
    return failures


class _CountingAdapter:
    """Wraps a live model adapter and counts real provider calls (honest ledger)."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        return self.inner.complete(request)


def run_dataset(dataset: dict, *, mode: str = "mock", model_adapter=None,
                model_id: str | None = None, max_calls: int | None = None) -> dict:
    if mode not in ("mock", "live"):
        raise ValueError("mode must be mock or live")
    cases = dataset["cases"]
    counter = _CountingAdapter(model_adapter) if model_adapter is not None else None
    reports = []
    for case in cases:
        if mode == "live" and max_calls is not None and counter is not None and counter.calls >= max_calls:
            reports.append({"id": case["id"], "outcome": "skipped", "reason": "max_calls reached"})
            continue
        call, rows = _make_call(case)
        by_id = {r["id"]: r for r in rows}
        adapter = OperatorTeamAdapter(
            resolve_material=lambda ref, by_id=by_id: by_id[ref["id"]],
            model_adapter=counter, mode=mode, model_id=model_id)
        try:
            result = adapter.invoke(call)
        except Exception as exc:  # noqa: BLE001 - eval must grade, never crash
            reports.append({"id": case["id"], "outcome": "fail",
                            "failures": [f"raised {type(exc).__name__}: {exc}"]})
            continue
        failures = _check(case.get("expect", {}), result, mode=mode)
        reports.append({"id": case["id"], "title": case.get("title"),
                        "outcome": "pass" if not failures else "fail",
                        "status": result.get("status"),
                        "error_issues": [i.get("reason") for i in result.get("issues") or []],
                        "failures": failures})
    passed = sum(1 for r in reports if r["outcome"] == "pass")
    graded = sum(1 for r in reports if r["outcome"] in ("pass", "fail"))
    return {
        "schema": "operator-eval.report.v1",
        "mode": mode,
        "is_mock": mode == "mock",
        "evidence_grade": "[Mock 流程]" if mode == "mock" else "[真实模型]",
        "predicts_real_traffic": False,
        "automatic_retry": False,
        "calls_used": counter.calls if counter is not None else 0,
        "pass_at_1": (passed / graded) if graded else None,
        "passed": passed, "graded": graded,
        "cases": reports,
    }


def repeat_dataset(dataset: dict, *, repeats: int, **kwargs) -> dict:
    """显式重复跑（≠自动重试）测 pass@k：case 在 k 次里至少一次过 = pass@k。"""
    runs = [run_dataset(dataset, **kwargs) for _ in range(max(1, repeats))]
    by_id: dict[str, list[bool]] = {}
    for run in runs:
        for case in run["cases"]:
            by_id.setdefault(case["id"], []).append(case["outcome"] == "pass")
    k = len(runs)
    pass_at_k = sum(1 for outs in by_id.values() if any(outs)) / len(by_id)
    pass_hat_k = sum(1 for outs in by_id.values() if all(outs)) / len(by_id)
    pass_at_1 = sum(run["pass_at_1"] or 0 for run in runs) / k
    return {
        "schema": "operator-eval.report.v1",
        "mode": runs[0]["mode"],
        "repeats": k,
        "is_mock": runs[0]["is_mock"],
        "evidence_grade": runs[0]["evidence_grade"],
        "predicts_real_traffic": False,
        "automatic_retry": False,
        "calls_used": sum(run["calls_used"] for run in runs),
        "pass_at_1": pass_at_1,
        f"pass_at_{k}": pass_at_k,
        f"pass_hat_{k}": pass_hat_k,
        "passed": runs[0]["passed"], "graded": runs[0]["graded"],
        "per_case": [{"id": cid, "passed_runs": sum(outs), "runs": len(outs)} for cid, outs in by_id.items()],
        "runs": [run["cases"] for run in runs],
    }


def format_report(report: dict) -> str:
    if "repeats" in report:
        k = report["repeats"]
        lines = [f"EVAL REPORT: operator prepare_brief ({report['mode']}, x{k} repeats)",
                 "=" * 48,
                 f"evidence: {report['evidence_grade']}  is_mock={report['is_mock']}  "
                 f"predicts_real_traffic=False  automatic_retry=False",
                 f"calls_used: {report['calls_used']}", ""]
        for case in report["per_case"]:
            lines.append(f"  {case['id']:<24} {case['passed_runs']}/{case['runs']} runs passed")
        lines += ["", f"pass@1: {report['pass_at_1']:.3f}",
                  f"pass@{k}: {report[f'pass_at_{k}']:.3f}   pass^{k}: {report[f'pass_hat_{k}']:.3f}"]
        return "\n".join(lines) + "\n"
    lines = [f"EVAL REPORT: operator prepare_brief ({report['mode']})",
             "=" * 48,
             f"evidence: {report['evidence_grade']}  is_mock={report['is_mock']}  "
             f"predicts_real_traffic=False  automatic_retry=False",
             f"calls_used: {report['calls_used']}",
             ""]
    for case in report["cases"]:
        mark = {"pass": "PASS", "fail": "FAIL", "skipped": "SKIP"}[case["outcome"]]
        line = f"  {case['id']:<24} {mark}"
        if case.get("status"):
            line += f"  (status={case['status']})"
        lines.append(line)
        for failure in case.get("failures", []):
            lines.append(f"      - {failure}")
        if case.get("reason"):
            lines.append(f"      - {case['reason']}")
    lines += ["", f"pass@1: {report['pass_at_1']}  ({report['passed']}/{report['graded']} graded)",
              "Status: " + ("READY FOR REVIEW" if report["passed"] == report["graded"] else "NEEDS WORK")]
    return "\n".join(lines) + "\n"
