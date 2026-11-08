"""Persist a frozen preview and show each simulated viewer only their own prefix."""
import json
from uuid import uuid4

from backend.agents import analyst, audience
from backend.api.previews import enqueue_preview
from backend.domain.errors import DomainError
from backend.domain.hashing import content_hash
from backend.domain.schemas import AudienceInput, ContentDelivery, PreviewSpec, Scenario
from backend.simulation.analysis_data import PreviewAnalysisInput, summarize_sessions
from backend.storage.db import utc_now
from backend.storage.queue import Queue
from .executor import encoded


def enqueue_requested_preview(work, db, task, version, brief):
    if not json.loads(task["input_json"]).get("preview_requested"):
        return
    scenario = Scenario(medium="text", segmenter_version="paragraph-v1", max_segments=8,
                        requested_seed=None, personas=[
                            {"id": "target_reader", "goal": brief.audience,
                             "knowledge": "第一次看到此内容", "preferences": ["具体示例"]},
                            {"id": "time_limited", "goal": "快速找到实用结论",
                             "knowledge": "对主题不熟悉", "preferences": ["简明直接"]},
                        ])
    spec = PreviewSpec(version_id=version["id"], content_hash=version["content_hash"], scenario=scenario)
    enqueue_preview(db, task["id"], spec, work.mode, utc_now())


def project_metrics(stats):
    return {
        "selected_sessions": stats["N"], "started": stats["S"], "completed": stats["C"],
        "exited": stats["exited"], "incomplete": stats["U"], "no_event_sessions": stats["Z"],
        "coverage_ratio": stats["coverage_ratio"]["value"], "completion_ratio": stats["completion_ratio"]["value"],
        "interaction_sessions": {key: value["numerator"] for key, value in stats["interaction_intentions"].items()},
        "interaction_ratios": {key: value["value"] for key, value in stats["interaction_intentions"].items()},
        "segments": [{"segment_id": row["segment_id"], "exposures": row["seen_sessions"],
                      "exits": row["exit_sessions"], "exit_rate": row["exit_rate"]["value"]} for row in stats["segments"]],
    }


def observations(work, session_id):
    return [{"event_id": row["id"], "event": json.loads(row["body_json"])} for row in work.read(
        "SELECT id,body_json FROM audience_events WHERE session_id=? ORDER BY ordinal", (session_id,), many=True)]


def simulate(work, preview_id, session, segments):
    persona = json.loads(session["persona_json"])
    records = observations(work, session["id"])
    for ordinal in range(session["cursor"], len(segments)):
        run = work.run()
        if run["active_ms"] >= json.loads(run["limits_json"]).get("max_active_seconds", 1200) * 1000:
            raise DomainError("BUDGET_EXCEEDED", "Preview active time limit reached", "Use a smaller preview scenario")
        snapshot = AudienceInput(persona=persona, current_segment=segments[ordinal], visible_history=segments[:ordinal],
                                 own_previous_reactions=[item["event"] for item in records])
        event_id = "ae_" + uuid4().hex

        def persist(db, result, call_id):
            if result.event is None:
                return
            event = result.event
            outcome = "exited" if event.action == "exit" else "completed" if ordinal + 1 == len(segments) else "active"
            seq = db.execute("SELECT coalesce(max(preview_seq),0)+1 FROM audience_events WHERE preview_id=?", (preview_id,)).fetchone()[0]
            db.execute("INSERT INTO audience_events(id,preview_id,session_id,ordinal,preview_seq,segment_id,call_id,body_json,action,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                       (event_id, preview_id, session["id"], ordinal, seq, event.segment_id, call_id,
                        encoded(event), event.action, utc_now()))
            db.execute("UPDATE audience_sessions SET cursor=?,outcome=?,stop_reason=? WHERE id=?",
                       (ordinal + 1, outcome, "viewer_exit" if outcome == "exited" else None, session["id"]))

        result = work.step(f"audience_{session['id']}_{ordinal}", "audience", snapshot, audience.SYSTEM).run(
            audience.AudienceAgent, "react", persist,
            mock_exit=work.mode == "mock" and persona["id"] == "time_limited" and ordinal == len(segments) - 1,
        )
        if result.event is None:
            error = result.error
            raise DomainError(error.code, error.cause_hint, error.next_action)
        records.append({"event_id": event_id, "event": result.event.model_dump(mode="json")})
        if result.event.action == "exit":
            break


def run_preview(work):
    preview = work.read(
        "SELECT p.*,s.body_json AS scenario,v.content_json FROM preview_runs p JOIN preview_scenarios s ON s.id=p.scenario_id "
        "JOIN content_versions v ON v.id=p.version_id AND v.task_id=p.task_id WHERE p.run_id=?",
        (work.lease.run_id,))
    scenario = Scenario.model_validate_json(preview["scenario"])
    content = ContentDelivery.model_validate_json(preview["content_json"])
    if content_hash(content) != preview["content_hash"]:
        raise DomainError("CONDITIONS_MISMATCH", "Preview version fingerprint changed", "Create a new preview")
    segments = [{"segment_id": "cover", "kind": "cover", "text": content.cover_copy}]
    segments.extend(segment.model_dump(exclude={"source_refs"}) for segment in content.segments[:scenario.max_segments - 1])
    with work.transaction() as db:
        db.execute("UPDATE preview_runs SET state='RUNNING',row_version=row_version+1 WHERE id=?", (preview["id"],))
        for ordinal, segment in enumerate(segments):
            db.execute("INSERT INTO preview_segments(preview_id,ordinal,segment_id,kind,text,source_segment_id) VALUES(?,?,?,?,?,?) "
                       "ON CONFLICT(preview_id,ordinal) DO NOTHING",
                       (preview["id"], ordinal, segment["segment_id"], segment["kind"], segment["text"],
                        segment["segment_id"] if ordinal else None))
        work.event(db, "audience", "模拟观众开始逐段试映")
    sessions = work.read("SELECT * FROM audience_sessions WHERE preview_id=? ORDER BY rowid", (preview["id"],), many=True)
    for session in sessions:
        if session["outcome"] not in {"completed", "exited"}:
            simulate(work, preview["id"], session, segments)
    sessions = work.read("SELECT * FROM audience_sessions WHERE preview_id=? ORDER BY rowid", (preview["id"],), many=True)
    traces = [{"session_id": row["id"], "persona_id": row["persona_id"], "outcome": row["outcome"],
               "events": observations(work, row["id"])} for row in sessions]
    snapshot = PreviewAnalysisInput(version_id=preview["version_id"], content_hash=preview["content_hash"], content=content,
                                    personas=scenario.personas, segments=segments, sessions=traces, max_segments=scenario.max_segments)
    metrics = project_metrics(summarize_sessions(traces, [row["segment_id"] for row in segments]))
    with work.transaction() as db:
        db.execute("UPDATE preview_runs SET metrics_json=? WHERE id=?", (encoded(metrics), preview["id"]))

    def persist(db, result, call_id):
        if result.error:
            return
        status = "skipped"
        if result.analysis_status == "completed":
            db.execute("INSERT INTO analyses(id,preview_id,call_id,body_json) VALUES(?,?,?,?)",
                       ("analysis_" + uuid4().hex, preview["id"], call_id, encoded(result.envelope.data)))
            status = "succeeded"
        db.execute("UPDATE preview_runs SET state='COMPLETED',analysis_status=?,row_version=row_version+1 WHERE id=?",
                   (status, preview["id"]))
        work.event(db, "analysis", result.envelope.summary)
        Queue.release_tx(db, work.lease, "SUCCEEDED", utc_now())

    result = work.step("analysis", "analyst", snapshot, analyst.SYSTEM).run(analyst.AnalystAgent, "run_preview", persist)
    if result.error:
        raise DomainError(result.error.code, result.error.cause_hint, result.error.next_action)
