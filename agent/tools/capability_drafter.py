#!/usr/bin/env python3
"""Draft and approve validated managed-resource capability overlays."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from agent.llm.client import chat_json, config_from_env
from agent.tools.capability_discovery import (
    CapabilityDiscoveryResult,
    validate_proposal_discovery,
)
from agent.tools.resource_catalog import (
    DEFAULT_CATALOG_PATH,
    DEFAULT_OVERRIDE_PATH,
    ResourceCapabilityCatalog,
    ResourceCapabilityDefinition,
    load_resource_catalog,
)


SYSTEM_PROMPT = """\
You draft Kubernetes managed-resource capability contracts.
Return one compact JSON object only. Never emit shell commands.
Use only safe Kubernetes object paths and do not set apiVersion, kind,
metadata.name, metadata.namespace, ownerReferences, or finalizers in baseObject.
"""


class ProposalModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schemaVersion: int = 1
    proposalId: str = ""
    sourceSpecDigest: str = ""
    status: str
    source: str
    unsupportedResources: list[str] = Field(default_factory=list)
    capabilities: list[ResourceCapabilityDefinition] = Field(
        default_factory=list
    )
    validationErrors: list[str] = Field(default_factory=list)
    approved: bool = False
    appliedTo: str = ""
    discoveryValidation: list[CapabilityDiscoveryResult] = Field(
        default_factory=list
    )
    discoveryErrors: list[str] = Field(default_factory=list)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Draft a schema-validated managed-resource capability."
    )
    parser.add_argument("--input", required=True, help="Operator spec YAML")
    parser.add_argument("--output", required=True, help="Proposal YAML")
    parser.add_argument(
        "--candidate",
        help="Use a candidate JSON/YAML file instead of calling the local LLM.",
    )
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG_PATH))
    parser.add_argument("--overrides", default=str(DEFAULT_OVERRIDE_PATH))
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--approve-proposal",
        help="Previously reviewed proposal YAML to apply.",
    )
    parser.add_argument(
        "--approval-digest",
        help="Exact proposalId shown during review.",
    )
    args = parser.parse_args()

    try:
        if args.approve:
            if not args.execute:
                raise ValueError("proposal approval requires --execute")
            if not args.approve_proposal or not args.approval_digest:
                raise ValueError(
                    "proposal approval requires --approve-proposal and "
                    "--approval-digest"
                )
            approved_path = approved_proposal_path(args.approve_proposal)
            proposal = load_proposal(approved_path)
            verify_discovery_approval(proposal)
            apply_proposal(
                proposal,
                Path(args.catalog),
                Path(args.overrides),
                expected_proposal_id=args.approval_digest,
                spec_path=Path(args.input),
            )
        else:
            proposal = draft_capabilities(
                Path(args.input),
                candidate_path=Path(args.candidate) if args.candidate else None,
                catalog_path=Path(args.catalog),
                override_path=Path(args.overrides),
                discover=True,
            )
    except (OSError, ValueError, ValidationError) as exc:
        print(f"capability proposal failed: {exc}", file=sys.stderr)
        return 2

    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        yaml.safe_dump(
            proposal.model_dump(mode="json"),
            sort_keys=False,
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "status": proposal.status,
                "unsupportedResources": proposal.unsupportedResources,
                "capabilityCount": len(proposal.capabilities),
                "approved": proposal.approved,
                "appliedTo": proposal.appliedTo,
                "discoveryPassed": bool(
                    proposal.discoveryValidation
                    and not proposal.discoveryErrors
                ),
                "discoveryErrors": proposal.discoveryErrors,
                "output": str(output),
            },
            ensure_ascii=False,
        )
    )
    return 0


def draft_capabilities(
    spec_path: Path,
    *,
    candidate_path: Path | None = None,
    catalog_path: Path = DEFAULT_CATALOG_PATH,
    override_path: Path = DEFAULT_OVERRIDE_PATH,
    discover: bool = False,
) -> ProposalModel:
    spec = read_mapping(spec_path)
    catalog = load_combined_catalog(catalog_path, override_path)
    controller = spec.get("controller") or {}
    requested = [
        str(item)
        for item in [
            *controller.get("managedResources", []),
            *controller.get("observedResources", []),
        ]
    ]
    supported = catalog.by_name()
    unsupported = [item for item in requested if item not in supported]
    if not unsupported:
        return ProposalModel(
            status="not-required",
            source="catalog",
            unsupportedResources=[],
        )

    if candidate_path:
        raw_candidate = read_mapping(candidate_path)
        source = "candidate"
    else:
        raw_candidate = llm_candidate(spec, unsupported, catalog)
        source = "local-llm"
    capabilities = parse_candidate(raw_candidate)
    proposed_kinds = {item.kind for item in capabilities}
    missing = [item for item in unsupported if item not in proposed_kinds]
    if missing:
        raise ValueError(
            "candidate did not define unsupported resources: "
            + ", ".join(missing)
        )
    validate_combined_catalog(catalog, capabilities)
    proposal = ProposalModel(
        status="pending-approval",
        source=source,
        sourceSpecDigest=file_digest(spec_path),
        unsupportedResources=unsupported,
        capabilities=capabilities,
    )
    if discover:
        try:
            proposal.discoveryValidation = validate_proposal_discovery(
                proposal.capabilities
            )
        except ValueError as exc:
            proposal.discoveryErrors = [str(exc)]
    proposal.proposalId = proposal_digest(proposal)
    return proposal


def llm_candidate(
    spec: dict[str, Any],
    unsupported: list[str],
    catalog: ResourceCapabilityCatalog,
) -> dict[str, Any]:
    schema = ResourceCapabilityDefinition.model_json_schema()
    prompt = (
        "Draft one capability per unsupported resource.\n"
        "Required JSON shape: {\"resources\":[...]}.\n"
        f"Unsupported resources: {json.dumps(unsupported)}\n"
        f"Operator spec: {json.dumps(spec, ensure_ascii=False)}\n"
        f"Capability JSON Schema: {json.dumps(schema)}\n"
        "Existing canonical kinds: "
        + json.dumps(sorted(item.kind for item in catalog.resources))
    )
    config = config_from_env(purpose="capability")
    raw = chat_json(SYSTEM_PROMPT, prompt, config)
    try:
        candidate = parse_json_object(raw)
        parse_candidate(candidate)
        return candidate
    except (ValueError, ValidationError) as first_error:
        repair = (
            "Repair this candidate to match the schema. Return JSON only.\n"
            f"Validation error: {first_error}\n"
            f"Candidate: {raw}\n"
            f"Schema: {json.dumps(schema)}"
        )
        return parse_json_object(chat_json(SYSTEM_PROMPT, repair, config))


def parse_candidate(
    value: dict[str, Any],
) -> list[ResourceCapabilityDefinition]:
    resources = value.get("resources")
    if resources is None and value.get("kind"):
        resources = [value]
    if not isinstance(resources, list) or not resources:
        raise ValueError("candidate requires a non-empty resources array")
    return [
        ResourceCapabilityDefinition.model_validate(item)
        for item in resources
    ]


def validate_combined_catalog(
    catalog: ResourceCapabilityCatalog,
    capabilities: list[ResourceCapabilityDefinition],
) -> ResourceCapabilityCatalog:
    return ResourceCapabilityCatalog.model_validate(
        {
            "version": catalog.version,
            "behaviorPrimitives": [
                item.model_dump(mode="json")
                for item in catalog.behaviorPrimitives
            ],
            "resources": [
                item.model_dump(mode="json")
                for item in [*catalog.resources, *capabilities]
            ],
        }
    )


def apply_proposal(
    proposal: ProposalModel,
    catalog_path: Path,
    override_path: Path,
    *,
    expected_proposal_id: str | None = None,
    spec_path: Path | None = None,
) -> None:
    actual_id = proposal_digest(proposal)
    if not proposal.proposalId or proposal.proposalId != actual_id:
        raise ValueError("capability proposal content no longer matches proposalId")
    if expected_proposal_id is not None and expected_proposal_id != actual_id:
        raise ValueError("capability approval digest does not match reviewed proposal")
    if proposal.status != "pending-approval" or proposal.approved:
        raise ValueError("only a pending capability proposal can be approved")
    if spec_path is not None:
        spec = read_mapping(spec_path)
        requested = {
            str(item)
            for item in (spec.get("controller") or {}).get(
                "managedResources", []
            )
        }
        if not set(proposal.unsupportedResources).issubset(requested):
            raise ValueError(
                "reviewed capability proposal does not match the current operator spec"
            )
    catalog = load_combined_catalog(catalog_path, override_path)
    base_catalog = load_base_catalog(catalog_path)
    existing = (
        read_mapping(override_path)
        if override_path.is_file()
        else {"version": 1, "resources": []}
    )
    resources = list(existing.get("resources") or [])
    proposed = {item.kind: item for item in proposal.capabilities}
    base_kinds = {
        item.kind
        for item in base_catalog.resources
    }
    conflict = base_kinds.intersection(proposed)
    if conflict:
        raise ValueError(
            "proposal cannot override built-in capabilities: "
            + ", ".join(sorted(conflict))
        )
    resources = [
        item for item in resources
        if str(item.get("kind") or "") not in proposed
    ]
    resources.extend(
        item.model_dump(mode="json", exclude_defaults=True)
        for item in proposal.capabilities
    )
    payload = {"version": 1, "resources": resources}
    ResourceCapabilityCatalog.model_validate(
        {
            "version": catalog.version,
            "behaviorPrimitives": [
                item.model_dump(mode="json")
                for item in catalog.behaviorPrimitives
            ],
            "resources": [
                item.model_dump(mode="json")
                for item in base_catalog.resources
            ] + resources,
        }
    )
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    load_resource_catalog.cache_clear()
    proposal.status = "approved"
    proposal.approved = True
    proposal.appliedTo = str(override_path)


def verify_discovery_approval(proposal: ProposalModel) -> None:
    if proposal.proposalId != proposal_digest(proposal):
        raise ValueError(
            "capability proposal changed before Kubernetes Discovery validation"
        )
    if proposal.discoveryErrors or not proposal.discoveryValidation:
        raise ValueError(
            "capability proposal requires a successful Kubernetes Discovery "
            "validation before approval"
        )
    current = validate_proposal_discovery(proposal.capabilities)
    expected = [
        item.model_dump(mode="json")
        for item in proposal.discoveryValidation
    ]
    actual = [item.model_dump(mode="json") for item in current]
    if expected != actual:
        raise ValueError(
            "Kubernetes Discovery changed after capability review; rerun dry-run"
        )


def load_proposal(path: Path) -> ProposalModel:
    return ProposalModel.model_validate(read_mapping(path))


def proposal_digest(proposal: ProposalModel) -> str:
    payload = {
        "schemaVersion": proposal.schemaVersion,
        "sourceSpecDigest": proposal.sourceSpecDigest,
        "unsupportedResources": proposal.unsupportedResources,
        "capabilities": [
            item.model_dump(mode="json") for item in proposal.capabilities
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def approved_proposal_path(value: str) -> Path:
    path = Path(value)
    resolved = (
        path.resolve()
        if path.is_absolute()
        else (REPO_ROOT / path).resolve()
    )
    try:
        resolved.relative_to((REPO_ROOT / "generated").resolve())
    except ValueError as exc:
        raise ValueError(
            "approved capability proposal must be inside generated/"
        ) from exc
    if resolved.suffix not in {".yaml", ".yml"}:
        raise ValueError("approved capability proposal must be YAML")
    return resolved


def load_combined_catalog(
    catalog_path: Path,
    override_path: Path,
) -> ResourceCapabilityCatalog:
    return load_resource_catalog(
        catalog_path,
        override_path=override_path,
    )


def load_base_catalog(catalog_path: Path) -> ResourceCapabilityCatalog:
    return load_resource_catalog(
        catalog_path,
        override_path=catalog_path.with_name(
            ".disabled-resource-capability-overrides.yaml"
        ),
    )


def read_mapping(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"expected YAML/JSON mapping: {path}")
    return data


def parse_json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw.strip())
    except json.JSONDecodeError as exc:
        raise ValueError(f"LLM returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("LLM capability candidate must be an object")
    return value


if __name__ == "__main__":
    raise SystemExit(main())
