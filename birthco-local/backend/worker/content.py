"""Content stages, with separate human decisions for the Brief and the result."""
import json
from uuid import uuid4

from backend.agents import director, editorial_reviewer, operator, pr_analyst, scout
from backend.domain.errors import DomainError, validate_brief_scope
from backend.domain.hashing import brief_hash, content_hash
from backend.domain.schemas import Brief, ContentCandidate, CreateTask, EditScope, Issue, Segment
from backend.storage.db import utc_now
from backend.validators.content import validate_content
from .executor import RULES, encoded


def materials(work):
    return work.read("SELECT id AS material_id,kind,label,text,source_url FROM materials WHERE task_id=? ORDER BY rowid",
                     (work.lease.task_id,), many=True)


def director_materials(rows):
    return [{k: row[k] for k in ("material_id", "kind", "label", "text")} for row in rows]


def envelope_error(envelope):
    issue = envelope.issues[0] if envelope.issues else None
    code = "INTERRUPTED" if issue and issue.id == "INTERRUPTED" else "MODEL_REJECTED"
    return DomainError(code, issue.reason if issue else "Agent did not produce an output",
                       issue.requested_change if issue else "Inspect the task and try again")


def wait_for_input(work, db, envelope):
    row = db.execute("SELECT pending_json FROM tasks WHERE id=?", (work.lease.task_id,)).fetchone()
    pending = json.loads(row["pending_json"] or "{}")
    pending.update(action="supply_input", questions=[q.model_dump() for q in envelope.questions])
    work.stop(db, "WAITING", "WAITING_INPUT", pending)


def commercial_handoff(work, intake, source, pending):
    if pending.get("pr_task"):
        return CreateTask.model_validate(pending["pr_task"])
    fields = {key: getattr(intake, key) for key in ("objective", "audience", "platform", "style")}
    fields.update({key: pending.get("answers", {}).get(key) or pending.get("answers", {}).get(f"missing_{key}")
                   for key in ("brand", "product")})
    for line in source["text"].splitlines():
        label, _, value = line.replace("：", ":", 1).partition(":")
        key = {"品牌": "brand", "产品": "product"}.get(label.strip())
        if key and not fields[key] and value.strip():
            fields[key] = value.strip()[:1000]
    snapshot = pr_analyst.PRAnalysisInput(
        analysis_requested=True, account_id=intake.account_id,
        client_brief={"label": source["label"], "text": source["text"], "authorized": True},
        intake=fields, requirements=intake.requirements, length_rule=intake.length_rule,
    )

    def persist(db, result, _):
        if result.envelope.status == "error":
            return
        if result.task_draft is None:
            wait_for_input(work, db, result.envelope)
            return
        handoff = result.task_draft.model_copy(update={"materials": intake.materials,
                                                       "preview_requested": intake.preview_requested})
        work.state(db, "PLANNING", {"pr_task": handoff.model_dump(mode="json")})
        work.event(db, "pr_intake", result.envelope.summary)

    key = f"pr_analysis_{pending.get('input_version', 0)}"
    result = work.step(key, "pr_analyst", snapshot, pr_analyst.SYSTEM).run(pr_analyst.PRAnalystAgent, "run", persist)
    if result.envelope.status == "error":
        raise envelope_error(result.envelope)
    return (result.task_draft.model_copy(update={"materials": intake.materials,
                                                "preview_requested": intake.preview_requested})
            if result.task_draft else None)


def plan(work):
    task = work.task()
    intake = CreateTask.model_validate_json(task["input_json"])
    rows = materials(work)
    pending = json.loads(task["pending_json"] or "{}")
    if task["current_brief_version"] is None:
        client = next((row for row in rows if row["kind"] == "source_text"
                       and row["label"].strip().casefold() in {"商单简报", "pr brief"}), None)
        if client is not None and intake.input_mode == "idea":
            intake = commercial_handoff(work, intake, client, pending)
            if intake is None:
                return
        scope = None
        draft = next((row for row in rows if row["kind"] == "existing_draft"), None)
        selection = pending.get("answers", {}).get("draft_scope", "")
        if draft and selection:
            ids = [seg["segment_id"] for seg in operator.draft_segments(draft["text"])]
            targets = ids if selection.strip() == "全部" else selection.replace("，", ",").split(",")
            targets = [value.strip() for value in targets]
            if targets and len(targets) == len(set(targets)) and set(targets) <= set(ids) and len(targets) <= 28:
                scope = EditScope(target_segment_ids=targets, preserve_segment_ids=[key for key in ids if key not in targets],
                                  allow_title_change=pending["answers"].get("allow_title") == "是",
                                  allow_cover_change=pending["answers"].get("allow_cover") == "是")

        def persist(db, result, _):
            envelope = result.envelope
            if envelope.status == "needs_input":
                wait_for_input(work, db, envelope)
            elif envelope.status == "ok":
                ids = {m["material_id"]: row["material_id"] for m, row in zip(operator.material_snapshot(intake), rows)}
                route = list(envelope.data.route)
                if intake.preview_requested and "preview" not in route:
                    route.insert(route.index("export") if "export" in route else len(route), "preview")
                brief = envelope.data.model_copy(update={"material_ids": [ids[key] for key in envelope.data.material_ids],
                                                        "route": route})
                db.execute("INSERT INTO briefs(task_id,version,body_json,brief_hash,rule_json,created_at) VALUES(?,1,?,?,?,?)",
                           (task["id"], encoded(brief), brief_hash(brief, RULES.model_dump()), encoded(RULES), utc_now()))
                db.execute("UPDATE tasks SET current_brief_version=1 WHERE id=?", (task["id"],))
                work.event(db, "operator", envelope.summary)

        key = f"prepare_brief_{pending.get('input_version', 0)}"
        planned = work.step(key, "operator", intake, operator.SYSTEM).run(
            operator.OperatorAgent, "run", persist, edit_scope=scope,
        )
        if planned.envelope.status == "error":
            raise envelope_error(planned.envelope)
        if planned.envelope.status == "needs_input":
            return

    brief = read_brief(work, work.task()["current_brief_version"])
    source_rows = [row for row in rows if row["kind"] != "existing_draft" and row["material_id"] in brief.material_ids]
    ran_scout = work.read("SELECT 1 FROM scouts WHERE run_id=?", (work.lease.run_id,))
    if source_rows and not ran_scout:
        snapshot = scout.ScoutInput(research_requested=True, account={
            "account_id": intake.account_id, "positioning": brief.objective, "audience": brief.audience,
            "style": intake.style}, brief=brief, materials=[{**dict(row), "authorized": True} for row in source_rows])

        def persist_scout(db, result, _):
            db.execute("INSERT INTO scouts(id,task_id,run_id,material_ids_json,result_json) VALUES(?,?,?,?,?)",
                       ("scout_" + uuid4().hex, task["id"], work.lease.run_id,
                        encoded([row["material_id"] for row in source_rows]), encoded(result.as_dict())))
            work.event(db, "scout", result.envelope.summary)

        result = work.step("capture_opportunities", "scout", snapshot, scout.SYSTEM).run(scout.ScoutAgent, "run", persist_scout)
        if result.envelope.status == "error":
            raise envelope_error(result.envelope)

    with work.transaction() as db:
        work.stop(db, "WAITING", "WAITING_CONFIRMATION", {"action": "confirm_brief"})


def read_brief(work, version):
    row = work.read("SELECT body_json FROM briefs WHERE task_id=? AND version=?", (work.lease.task_id, version))
    return Brief.model_validate_json(row["body_json"])


def original_content(rows):
    draft = next(row for row in rows if row["kind"] == "existing_draft")
    return ContentCandidate(titles=[], cover_copy=None, segments=[
        Segment(**seg, kind="body", source_refs=[draft["material_id"]])
        for seg in operator.draft_segments(draft["text"])
    ])


def save_version(work, db, run, candidate, version_id, parent):
    task_id = work.lease.task_id
    ordinal = db.execute("SELECT coalesce(max(ordinal),0)+1 FROM content_versions WHERE task_id=?", (task_id,)).fetchone()[0]
    db.execute("INSERT INTO content_versions(id,task_id,run_id,ordinal,parent_id,brief_version,brief_hash,content_json,content_hash,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
               (version_id, task_id, run["id"], ordinal, parent, run["brief_version"], run["brief_hash"],
                encoded(candidate), content_hash(candidate), utc_now()))
    db.execute("UPDATE tasks SET head_version_id=? WHERE id=?", (version_id, task_id))


def edit_requests(locations, text):
    return [Issue(id=f"edit_{index}", severity="advisory", location=location, reason="用户修改意见", requested_change=text)
            for index, location in enumerate(locations, 1)]


def draft_content(work, run, task, brief, rows):
    phase = run["phase"]
    payload = {"confirmed": True, "brief": brief, "frozen_rules": RULES,
               "style": CreateTask.model_validate_json(task["input_json"]).style, "materials": director_materials(rows),
               "reserved_segment_ids": ["s_" + uuid4().hex for _ in range(32)]}
    parent = task["head_version_id"]
    entry = director.DirectorInput
    if phase == "repair":
        base = work.read("SELECT content_json FROM content_versions WHERE id=? AND task_id=?", (parent, task["id"]))
        candidate = ContentCandidate.model_validate_json(base["content_json"])
        repair = json.loads(task["pending_json"] or "{}")
        requests = [Issue.model_validate(item) for item in repair.get("issues", [])]
        locations = {issue.location for issue in requests}
        scope = EditScope(target_segment_ids=[s.segment_id for s in candidate.segments if s.segment_id in locations],
                          preserve_segment_ids=[s.segment_id for s in candidate.segments if s.segment_id not in locations],
                          allow_title_change="titles" in locations, allow_cover_change="cover" in locations)
        payload.update(brief=brief.model_copy(update={"input_mode": "existing_draft", "edit_scope": scope}),
                       base_version_id=parent, base_content=candidate, base_content_hash=content_hash(candidate),
                       edit_requests=requests)
        entry = director.WorkflowRevisionInput
    elif brief.input_mode == "existing_draft":
        candidate = original_content(rows)
        scope = brief.edit_scope
        locations = list(scope.target_segment_ids)
        if scope.allow_title_change:
            locations.append("titles")
        if scope.allow_cover_change:
            locations.append("cover")
        payload.update(base_version_id="original_" + task["id"], base_content=candidate,
                       base_content_hash=content_hash(candidate),
                       edit_requests=edit_requests(locations, brief.requirements[0].text))
    payload["brief_hash"] = brief_hash(payload["brief"], RULES.model_dump())
    snapshot = entry(**payload)

    def persist(db, result, _):
        if result.envelope.status == "needs_input":
            wait_for_input(work, db, result.envelope)
        elif result.envelope.status == "ok":
            value = ContentCandidate.model_validate(result.envelope.data.model_dump(exclude={"change_log"}))
            save_version(work, db, run, value, result.version_id, parent)
            work.phase(db, "rule", "VALIDATING")

    result = work.step(phase, "director", snapshot, director.SYSTEM).run(director.ContentDirectorAgent, "run", persist)
    if result.envelope.status == "error":
        raise envelope_error(result.envelope)


def validate_version(work, version, candidate, brief):
    report = validate_content(version["id"], candidate, brief)
    with work.transaction() as db:
        db.execute("INSERT INTO rule_reports(id,task_id,version_id,rule_version,passed,body_json) VALUES(?,?,?,?,?,?)",
                   ("rules_" + uuid4().hex, version["task_id"], version["id"], report.rule_version, report.passed, encoded(report)))
        work.phase(db, "review", "VALIDATING")


def review_version(work, run, version, candidate, brief, rows):
    snapshot = editorial_reviewer.ReviewInput(confirmed=True, version_id=version["id"], content_hash=version["content_hash"],
                                               brief=brief, content=candidate, materials=director_materials(rows))

    def persist(db, result, call_id):
        envelope = result.envelope
        value = envelope.data
        if value is None:
            return
        if call_id is not None:
            db.execute("INSERT INTO editorial_reviews(id,task_id,version_id,call_id,overall,body_json) VALUES(?,?,?,?,?,?)",
                       ("review_" + uuid4().hex, version["task_id"], version["id"], call_id, value.overall, encoded(value)))
        if value.overall == "pass" or (work.mode == "mock" and result.rule_report.passed):
            work.event(db, "review", envelope.summary)
            work.phase(db, "export", "EXPORTING")
            return
        allowed = {s.segment_id for s in candidate.segments} | {"titles", "cover"}
        unique = {issue.location: issue for issue in value.issues if issue.location in allowed}
        if value.overall == "revise" and brief.input_mode == "idea" and not run["repair_count"] and unique:
            db.execute("UPDATE runs SET repair_count=1,phase='repair' WHERE id=?", (run["id"],))
            work.state(db, "REVISING", {"issues": [item.model_dump(mode="json") for item in unique.values()]})
            work.event(db, "repair", "Independent review requested a bounded repair")
        else:
            work.stop(db, "WAITING", "NEEDS_REVIEW", {"action": "review_content", "issues": [i.model_dump() for i in value.issues]})

    result = work.step(f"review_{version['ordinal']}", "reviewer", snapshot, editorial_reviewer.SYSTEM).run(
        editorial_reviewer.EditorialReviewerAgent, "run", persist,
    )
    if result.envelope.status == "error":
        raise envelope_error(result.envelope)


def run_content(work):
    while (run := work.run())["state"] == "RUNNING":
        phase = run["phase"]
        if phase in {"planning", "operator"}:
            plan(work)
            return
        task = work.task()
        brief = read_brief(work, run["brief_version"])
        rows = [row for row in materials(work) if row["material_id"] in brief.material_ids]
        draft = next((row for row in rows if row["kind"] == "existing_draft"), None)
        draft_ids = {seg["segment_id"] for seg in operator.draft_segments(draft["text"])} if draft else set()
        validate_brief_scope(brief, material_kinds={row["material_id"]: row["kind"] for row in rows},
                             existing_segment_ids=draft_ids, p0_only=False)
        if phase in {"draft", "repair"}:
            draft_content(work, run, task, brief, rows)
            continue
        version = work.read("SELECT * FROM content_versions WHERE id=? AND task_id=?", (task["head_version_id"], task["id"]))
        candidate = ContentCandidate.model_validate_json(version["content_json"])
        if phase == "rule":
            validate_version(work, version, candidate, brief)
        elif phase == "review":
            review_version(work, run, version, candidate, brief, rows)
        elif phase == "export":
            from .preview import enqueue_requested_preview

            with work.transaction() as db:
                db.execute("UPDATE tasks SET ready_version_id=? WHERE id=?", (version["id"], task["id"]))
                enqueue_requested_preview(work, db, task, version, brief)
                work.stop(db, "SUCCEEDED", "READY", {"action": "accept_or_revise"})
        else:
            raise DomainError("INVALID_TRANSITION", "Unknown content phase", "Inspect the worker run")
