"""Public one-way Controller generation pipeline."""

from __future__ import annotations

from typing import Any

from agent.tools.controller_ir import ControllerGenerationIR
from agent.tools.controller_ir_builder import build_controller_ir
from agent.tools.controller_renderer import render_controller


def generate_controller(
    operator_spec: dict[str, Any],
) -> tuple[ControllerGenerationIR, str]:
    """Convert an Operator spec once, then render only from the resulting IR."""
    ir = build_controller_ir(operator_spec)
    return ir, render_controller(ir)
