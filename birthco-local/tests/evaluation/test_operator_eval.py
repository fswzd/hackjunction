"""评测回归锁定：mock 档数据集必须全过（pass^3，确定性）。"""
from pathlib import Path

from backend.evaluation.operator_eval import load_dataset, run_dataset

DATASET = Path(__file__).resolve().parents[1] / "fixtures" / "operator_eval" / "dataset.json"


def test_mock_dataset_passes_three_consecutive_runs():
    dataset = load_dataset(DATASET)
    for _ in range(3):  # pass^3: 三次连续全过
        report = run_dataset(dataset, mode="mock")
        assert report["passed"] == report["graded"] == len(dataset["cases"]), report["cases"]
        assert report["is_mock"] is True
        assert report["predicts_real_traffic"] is False
        assert report["automatic_retry"] is False
        assert report["calls_used"] == 0
