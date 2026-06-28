"""Cross-capability policies applied before IR is accepted."""

from __future__ import annotations

from agent.tools.controller_ir import FieldMapping, StaticMutation


def validate_mutation_contract(
    kind: str,
    mappings: list[FieldMapping],
    static_mutations: list[StaticMutation],
) -> None:
    """Reject multiple sources that attempt to own one target path."""
    targets: dict[str, str] = {}
    for mapping in mappings:
        previous = targets.get(mapping.target_path)
        if previous and previous != mapping.source_path:
            raise ValueError(
                f"conflicting {kind} mutation target "
                f"{mapping.target_path}: {previous} and "
                f"{mapping.source_path}"
            )
        targets[mapping.target_path] = mapping.source_path
    for mutation in static_mutations:
        previous = targets.get(mutation.target_path)
        if previous:
            raise ValueError(
                f"conflicting {kind} mutation target "
                f"{mutation.target_path}: {previous} and static value"
            )
        targets[mutation.target_path] = "static value"
