"""Guards the layer boundaries in SR_Technical_Document §2.2 (L0 → L5).

Walks the AST of every module under src/sr_agent and fails on an import edge
that points at a higher layer. Permanent test: move the code, do not widen it.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "sr_agent"

LAYER: dict[str, int] = {
    "config": 0,
    "data": 1,
    "levels": 2,
    "labels": 2,
    "features": 3,
    "simulate": 3,
    "models": 4,
    "calibrate": 4,
    "validation": 4,
    "agent": 5,
    "api": 5,
    "reporting": 5,
    "ops": 5,
    "cli": 5,
}


def _package_of(module_path: Path) -> str:
    rel = module_path.relative_to(SRC).with_suffix("")
    return rel.parts[0] if rel.parts else ""


def _imports(tree: ast.AST) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            out.add(node.module)
    return out


def test_no_upward_imports() -> None:
    violations: list[str] = []
    for path in SRC.rglob("*.py"):
        pkg = _package_of(path)
        if pkg not in LAYER:
            continue
        for mod in _imports(ast.parse(path.read_text(encoding="utf-8"))):
            if not mod.startswith("sr_agent."):
                continue
            target = mod.split(".")[1]
            if target in LAYER and LAYER[target] > LAYER[pkg]:
                violations.append(
                    f"{path.relative_to(SRC)} (L{LAYER[pkg]}) imports {mod} (L{LAYER[target]})"
                )
    assert not violations, "\n".join(violations)


def test_every_layer_package_exists() -> None:
    for name in LAYER:
        if name == "cli":
            assert (SRC / "cli.py").exists()
        else:
            assert (SRC / name / "__init__.py").exists(), name
