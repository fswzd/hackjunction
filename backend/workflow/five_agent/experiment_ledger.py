"""Append-only experiment lineage over the workflow artifact repository."""
from .repository import DomainError, object_hash


def record(repo, task_id, run_id, stage, payload):
    entry = {"stage": stage, **payload}
    key = "experiment_" + object_hash({"task": task_id, "run": run_id, "entry": entry})[:24]
    return repo.save_artifact(key, task_id, run_id, "experiment_entry", entry)


def history_for_preview(repo, account_id, preview_id):
    preview = repo.get_artifact(preview_id)
    if preview["kind"] != "preview" or repo.get_task(preview["task_id"])["account_id"] != account_id:
        raise DomainError("preview outside account scope", "SCOPE_DENIED")
    if preview["payload"]["scenario"].get("blind") is True:
        raise DomainError("blind preview cannot read experiment history", "SCOPE_DENIED")
    return repo.find_artifacts(preview["task_id"], "experiment_entry")
