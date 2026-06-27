#!/usr/bin/env python3
"""Draft and approve validated managed-resource capability overlays."""

from __future__ import annotations

import argparse
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
    status: str
    source: str
    unsupportedResources: list[str] = Field(default_factory=list)
    capabilities: list[ResourceCapabilityDefinition] = Field(
        default_factory=list
    )
    validationErrors: list[str] = Field(default_factory=list)
    approved: bool = False
    appliedTo: str = ""


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
    args = parser.parse_args()

    try:
        proposal = draft_capabilities(
            Path(args.input),
            candidate_path=Path(args.candidate) if args.candidate else None,
            catalog_path=Path(args.catalog),
            override_path=Path(args.overrides),
        )
        if args.approve and args.execute and proposal.capabilities:
            apply_proposal(
                proposal,
                Path(args.catalog),
                Path(args.overrides),
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
) -> ProposalModel:
    spec = read_mapping(spec_path)
    catalog = load_combined_catalog(catalog_path, override_path)
    requested = [
        str(item)
        for item in (spec.get("controller") or {}).get(
            "managedResources", []
        )
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
    return ProposalModel(
        status="pending-approval",
        source=source,
        unsupportedResources=unsupported,
        capabilities=capabilities,
    )


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
) -> None:
    catalog = load_combined_catalog(catalog_path, override_path)
    validate_combined_catalog(catalog, proposal.capabilities)
    existing = (
        read_mapping(override_path)
        if override_path.is_file()
        else {"version": 1, "resources": []}
    )
    resources = list(existing.get("resources") or [])
    resources.extend(
        item.model_dump(mode="json", exclude_defaults=True)
        for item in proposal.capabilities
    )
    payload = {"version": 1, "resources": resources}
    override_path.parent.mkdir(parents=True, exist_ok=True)
    override_path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )
    load_resource_catalog.cache_clear()
    proposal.status = "approved"
    proposal.approved = True
    proposal.appliedTo = str(override_path)


def load_combined_catalog(
    catalog_path: Path,
    override_path: Path,
) -> ResourceCapabilityCatalog:
    return load_resource_catalog(
        catalog_path,
        override_path=override_path,
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
