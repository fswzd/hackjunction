"""Extract the five-agent contract resources from the team handoff package.

Copies agent-interface.json and the domain DTO subset used by the five-agent
contract into backend/workflow/five_agent/resources/, so this checkout is
self-contained. Provenance is recorded in the generated manifest.

Usage:
  python tools/extract_schemas.py --handoff-root <.../creator-agent-team>

The handoff root must contain docs/agent-system/implementation-design/.
"""
import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESOURCES = REPO_ROOT / "backend" / "workflow" / "five_agent" / "resources"

NEEDED_DTOS = [
    # result envelope pieces
    "Question", "Issue",
    # action output DTOs
    "Brief", "ContentCandidate", "Revision", "EditorialReview",
    "OpportunitySet", "Analysis", "AudienceEvent", "AudienceInput",
    # program-side DTOs used by rules/metrics/gates
    "RuleResult", "RuleReport", "RevisionRequest", "Metrics", "SegmentMetric",
    "Scenario", "PreviewSpec", "EditScope", "Segment", "Persona", "VisibleSegment",
    "Change", "Opportunity", "Finding",
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--handoff-root", type=Path, required=True,
                        help="Path to creator-agent-team (the packet root)")
    args = parser.parse_args()
    root: Path = args.handoff_root
    design = root / "docs" / "agent-system" / "implementation-design"
    iface_path = design / "langgraph" / "five-agent" / "agent-interface.json"
    schemas_path = design / "contracts" / "schemas.json"
    for p in (iface_path, schemas_path):
        if not p.is_file():
            raise SystemExit(f"missing handoff file: {p}")

    RESOURCES.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(iface_path, RESOURCES / "agent-interface.json")

    domain = json.loads(schemas_path.read_text(encoding="utf-8"))
    subset = {k: domain[k] for k in NEEDED_DTOS if k in domain}
    missing = [k for k in NEEDED_DTOS if k not in domain]
    out_path = RESOURCES / "domain_schemas.json"
    out_path.write_text(json.dumps(subset, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")

    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "agent-interface.json": {"path": str(iface_path), "sha256": hashlib.sha256(iface_path.read_bytes()).hexdigest()},
            "schemas.json": {"path": str(schemas_path), "sha256": hashlib.sha256(schemas_path.read_bytes()).hexdigest()},
        },
        "extracted_dtos": sorted(subset),
        "missing_dtos": missing,
    }
    (RESOURCES / "provenance.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"copied agent-interface.json; extracted {len(subset)} DTOs; missing={missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
