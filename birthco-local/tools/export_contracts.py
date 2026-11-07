"""Generate JSON Schema, OpenAPI and TypeScript from the application models."""
import argparse
import importlib.util
import inspect
import json
from pathlib import Path
import sys
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("application_models", ROOT / "backend/domain/schemas.py")
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def outputs():
    models = {n: c for n, c in vars(m).items() if inspect.isclass(c) and issubclass(c, BaseModel) and c.__module__ == m.__name__ and n not in {"Model", "Envelope", "ApiSuccess", "ToolResult"}}
    models.update({"Role_" + role.replace("-", "_"): cls for role, cls in m.ROLE_MODELS.items()})
    models.update({"Tool_" + tool: cls for tool, cls in m.TOOL_MODELS.items()})
    # method,path,input type,output type,success code,owner
    routes = [
        ("get", "/api/v1/session", None, m.SessionRead, 200, "A02c"),
        ("post", "/api/v1/session/operator", m.OperatorUnlock, m.SessionRead, 200, "A05b"),
        ("get", "/api/v1/accounts", None, list[m.AccountRead], 200, "A02c"),
        ("post", "/api/v1/accounts", m.AccountCreate, m.AccountRead, 201, "A02c"),
        ("post", "/api/v1/tasks", m.CreateTask, m.TaskSummary, 202, "A02c"),
        ("get", "/api/v1/tasks", None, list[m.TaskSummary], 200, "A02c"),
        ("get", "/api/v1/tasks/{task_id}", None, m.TaskSummary, 200, "A02c"),
        ("get", "/api/v1/tasks/{task_id}/materials", None, list[m.MaterialRead], 200, "A02c"),
        ("post", "/api/v1/tasks/{task_id}/input", m.UpdateInput, m.TaskSummary, 202, "A03b"),
        ("get", "/api/v1/tasks/{task_id}/brief", None, m.BriefRead, 200, "A03b"),
        ("put", "/api/v1/tasks/{task_id}/brief", m.EditBrief, m.BriefRead, 200, "A03b"),
        ("post", "/api/v1/tasks/{task_id}/confirm", m.ConfirmBrief, m.TaskSummary, 202, "A03b"),
        ("post", "/api/v1/tasks/{task_id}/cancel", m.Expected, m.TaskSummary, 200, "A03b"),
        ("post", "/api/v1/tasks/{task_id}/resume", m.Resume, m.TaskSummary, 202, "A03b"),
        ("get", "/api/v1/tasks/{task_id}/events", None, m.EventPage, 200, "A02c"),
        ("get", "/api/v1/tasks/{task_id}/versions", None, list[m.VersionRead], 200, "A04a"),
        ("get", "/api/v1/tasks/{task_id}/versions/{version_id}", None, m.VersionRead, 200, "A04a"),
        ("post", "/api/v1/tasks/{task_id}/accept", m.AcceptVersion, m.TaskSummary, 200, "A04b"),
        ("post", "/api/v1/tasks/{task_id}/exports", m.ExportVersion, m.TaskSummary, 202, "A04b"),
        ("get", "/api/v1/tasks/{task_id}/artifacts", None, list[m.ArtifactRead], 200, "A04b"),
        ("post", "/api/v1/tasks/{task_id}/feedback", m.FeedbackCreate, m.FeedbackRead, 201, "A05b"),
        ("get", "/api/v1/tasks/{task_id}/feedback", None, list[m.FeedbackRead], 200, "A05b"),
        ("get", "/api/v1/tasks/{task_id}/usage", None, m.Usage, 200, "A05b"),
        ("post", "/api/v1/orders", m.OrderCreate, m.OrderRead, 201, "A05b"),
        ("get", "/api/v1/orders", None, list[m.OrderRead], 200, "A05b"),
        ("post", "/api/v1/orders/{order_id}/receipts", m.ReceiptCreate, m.ReceiptRead, 201, "A05b"),
        ("get", "/api/v1/accounts/{account_id}/memories", None, list[m.MemoryRead], 200, "A06"),
        ("post", "/api/v1/accounts/{account_id}/memories", m.MemoryCreate, m.MemoryRead, 201, "A06"),
        ("post", "/api/v1/accounts/{account_id}/memories/{memory_id}/decisions", m.MemoryDecision, m.MemoryRead, 200, "A06"),
        ("post", "/api/v1/scouts", m.ScoutRequest, m.ScoutRead, 202, "A06"),
        ("get", "/api/v1/scouts/{scout_id}", None, m.ScoutRead, 200, "A06"),
        ("post", "/api/v1/previews/preflight", m.PreviewSpec, m.PreflightRead, 200, "A07b"),
        ("post", "/api/v1/previews", m.PreviewCreate, m.PreviewRead, 202, "A07b"),
        ("get", "/api/v1/previews/{preview_id}", None, m.PreviewRead, 200, "A07b"),
        ("get", "/api/v1/previews/{preview_id}/events", None, m.AudienceEventPage, 200, "A07b"),
        ("post", "/api/v1/previews/{preview_id}/cancel", m.Expected, m.PreviewRead, 200, "A07b"),
        ("post", "/api/v1/previews/{preview_id}/resume", m.Resume, m.PreviewRead, 202, "A07b"),
        ("get", "/api/v1/analyses/{analysis_id}", None, m.AnalysisRead, 200, "A08a"),
        ("post", "/api/v1/tasks/{task_id}/revisions", m.RevisionRequest, m.RevisionRead, 202, "A08a"),
        ("post", "/api/v1/tasks/{task_id}/restore-head", m.RestoreHead, m.TaskSummary, 200, "A08a"),
        ("get", "/api/v1/revisions/{revision_id}", None, m.RevisionRead, 200, "A08a"),
        ("post", "/api/v1/revisions/{revision_id}/cancel", m.Expected, m.RevisionRead, 200, "A08a"),
        ("post", "/api/v1/revisions/{revision_id}/resume", m.Resume, m.RevisionRead, 202, "A08a"),
        ("post", "/api/v1/comparisons", m.CompareCreate, m.ComparisonRead, 201, "A08a"),
        ("get", "/api/v1/comparisons/{comparison_id}", None, m.ComparisonRead, 200, "A08a"),
        ("post", "/api/v1/experiments/preflight", m.ExperimentSpec, m.ExperimentPreflightRead, 200, "A08a"),
        ("post", "/api/v1/experiments", m.ExperimentCreate, m.ExperimentRead, 202, "A08a"),
        ("get", "/api/v1/experiments/{experiment_id}", None, m.ExperimentRead, 200, "A08a"),
    ]
    defs, catalog = {}, {}

    def schema_for(cls):
        schema = cls.model_json_schema(ref_template="#/components/schemas/{model}")
        defs.update(schema.pop("$defs", {}))
        return schema

    for name, cls in models.items():
        cls.model_rebuild(_types_namespace=vars(m))
        defs[name] = schema_for(cls)
        catalog[name] = cls.model_json_schema()
    paths = {}
    for method, path, request, response, code, owner in routes:
        model = m.ApiSuccess[response]
        name = model.__name__
        defs[name] = schema_for(model)
        operation = {"operationId": method + "_" + path.replace("/api/v1/", "").replace("/", "_").replace("{", "").replace("}", ""), "x-owner": owner, "responses": {str(code): {"description": "Committed response; asynchronous work not yet complete" if code == 202 else "Success", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/" + name}}}}}, "parameters": []}
        import re
        for parameter in re.findall(r"\{(\w+)\}", path):
            operation["parameters"].append({"name": parameter, "in": "path", "required": True, "schema": {"type": "string", "pattern": "^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$"}})
        if method in {"post", "put"}:
            operation["parameters"].extend([{"name": "Idempotency-Key", "in": "header", "required": True, "schema": {"type": "string", "minLength": 16, "maxLength": 128}}, {"name": "X-CSRF-Token", "in": "header", "required": True, "schema": {"type": "string"}}])
        if request:
            operation["requestBody"] = {"required": True, "content": {"application/json": {"schema": {"$ref": "#/components/schemas/" + request.__name__}}}}
        for err in (400, 401, 403, 404, 409, 413, 422, 503):
            operation["responses"][str(err)] = {"description": "Typed error; see design section 5", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiFailure"}}}}
        if method == "get" and path.endswith("/events"):
            operation["parameters"].extend([{"name": "after_seq", "in": "query", "schema": {"type": "integer", "minimum": 0, "default": 0}}, {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 100}}])
        if method == "get" and path in {"/api/v1/tasks", "/api/v1/orders"}:
            operation["parameters"].extend([{"name": "account_id", "in": "query", "required": True, "schema": {"type": "string"}}, {"name": "limit", "in": "query", "schema": {"type": "integer", "minimum": 1, "maximum": 100, "default": 100}}])
        if path == "/api/v1/session":
            operation["security"] = []
        paths.setdefault(path, {})[method] = operation
    paths["/api/v1/artifacts/{artifact_id}/download"] = {"get": {"operationId": "download_artifact", "x-owner": "A04b", "parameters": [{"name": "artifact_id", "in": "path", "required": True, "schema": {"type": "string"}}], "responses": {"200": {"description": "Hash-verified UTF-8 bytes; Content-Disposition attachment", "content": {"text/plain": {"schema": {"type": "string", "format": "binary"}}}}, "409": {"description": "ARTIFACT_MISSING or corrupt", "content": {"application/json": {"schema": {"$ref": "#/components/schemas/ApiFailure"}}}}}}}
    import re
    names = {name: re.sub(r"[^A-Za-z0-9._-]", "_", name) for name in defs}
    if len(set(names.values())) != len(names):
        raise ValueError("OpenAPI component name collision")

    def normalize(value):
        if isinstance(value, dict):
            value = {k: normalize(v) for k, v in value.items()}
            ref = value.get("$ref")
            prefix = "#/components/schemas/"
            if isinstance(ref, str) and ref.startswith(prefix):
                value["$ref"] = prefix + names[ref[len(prefix):]]
        elif isinstance(value, list):
            value = [normalize(v) for v in value]
        return value

    document = {"openapi": "3.1.0", "info": {"title": "Creator Local DESIGN contract", "version": "1.1.0"}, "servers": [{"url": "http://127.0.0.1:5000"}], "security": [{"LocalSession": []}], "paths": normalize(paths), "components": {"securitySchemes": {"LocalSession": {"type": "apiKey", "in": "cookie", "name": "birthco_session"}}, "schemas": {names[k]: normalize(v) for k, v in defs.items()}}}
    return {ROOT / "contracts/schemas.json": catalog, ROOT / "contracts/openapi.json": document}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    for path, value in outputs().items():
        content = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, indent=2) + "\n"
        if args.check:
            if not path.exists() or path.read_text(encoding="utf-8") != content:
                raise SystemExit(f"STALE: {path.name}; run export_contracts.py")
        else:
            path.write_text(content, encoding="utf-8")
    print("PASS: application schemas and OpenAPI are current" if args.check else "Generated application schemas and OpenAPI")
