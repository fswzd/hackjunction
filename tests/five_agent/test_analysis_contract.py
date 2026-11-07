"""跨层契约：mock 分析产物不得宣称同条件或因果结论（审计 F-A3）。"""
from types import SimpleNamespace

from backend.workflow.five_agent.adapters import gen_analysis

# 与业务侧 comparison_context 单版本分支逐字一致（birthco-local/backend/simulation/analysis_data.py）；
# 配套 birthco-local/tests/agents/test_analyst.py::test_single_version_comparison_reason_is_frozen 同步钉住。
SINGLE_VERSION_REASON = "单版本分析：没有可比较的第二版。"


class _Resolver:
    def preview(self, preview_id):
        return {"events": [{"id": "obs_1", "payload": {"segment_id": "s1"}},
                           {"id": "obs_2", "payload": {"segment_id": "s1"}},
                           {"id": "obs_3", "payload": {"segment_id": "s2"}}]}

    def artifact(self, ref):
        return {"payload": {"segments": [{"segment_id": "s1", "exposures": 2, "exits": 1, "exit_rate": 0.5},
                                         {"segment_id": "s2", "exposures": 1, "exits": 0, "exit_rate": 0.0}]}}


def _mock_analysis():
    call = SimpleNamespace(input={"preview_ref": {"id": "pv_1"}, "metrics_ref": {"id": "metrics_1"}})
    return gen_analysis(call, _Resolver())["data"]


def test_mock_analysis_never_claims_verified_conditions():
    comparison = _mock_analysis()["comparison"]
    assert comparison["conditions_match"] is False
    assert comparison["reason"] == SINGLE_VERSION_REASON
    assert comparison["summary"].strip()
    assert "因果" in comparison["summary"] and "不宣称" in comparison["summary"]


def test_mock_findings_stay_descriptive_and_reference_real_observations():
    data = _mock_analysis()
    assert data["findings"], "预置场景应产生 finding"
    valid_refs = {"obs_1", "obs_2", "obs_3"}
    for finding in data["findings"]:
        assert finding["observation_refs"] and set(finding["observation_refs"]) <= valid_refs
        assert finding["interpretation"].startswith("本次模拟中")
        assert "不证明" in finding["interpretation"]
        assert finding["alternative_explanation"].strip() and finding["suggested_edit"].strip()
    assert data["next_experiment"].strip()
