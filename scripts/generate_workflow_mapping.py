#!/usr/bin/env python3
"""Regenerate configs/workflow-mapping.json.

The mapping is derived from the parameter registry and the reference ComfyUI
workflow, so it cannot drift from either. tests/unit/test_parameter_mapping.py
asserts that the generated values still match the workflow.

    python scripts/generate_workflow_mapping.py
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPO_ROOT / "yue2_full.json"
REGISTRY = REPO_ROOT / "configs" / "parameter-registry.json"
OUTPUT = REPO_ROOT / "configs" / "workflow-mapping.json"


def main() -> int:
    workflow = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    registry = json.loads(REGISTRY.read_text(encoding="utf-8"))

    nodes = {
        node["id"]: {
            "id": node["id"],
            "type": node["type"],
            "title": node.get("title"),
            # ComfyUI mode 4 means the node is bypassed in the saved graph.
            "bypassed": node.get("mode", 0) == 4,
            "widgets": node.get("widgets_values_named") or {},
        }
        for node in workflow["nodes"]
    }
    by_type: dict[str, list[dict]] = {}
    for node in nodes.values():
        by_type.setdefault(node["type"], []).append(node)

    mapping = []
    for parameter in registry["parameters"]:
        comfy = parameter["comfy"]
        node_type, widget = comfy.get("node"), comfy.get("widget")
        observed = None
        if node_type and widget:
            for node in by_type.get(node_type, []):
                if widget in node["widgets"]:
                    observed = node["widgets"][widget]
                    break
        mapping.append(
            {
                "parameter": parameter["key"],
                "label": parameter["label"],
                "kind": parameter["kind"],
                "native": parameter["native"],
                "comfy_node_type": node_type,
                "comfy_widget": widget,
                "comfy_note": comfy.get("note"),
                "workflow_value": observed,
            }
        )

    document = {
        "schema_version": 1,
        "source_workflow": WORKFLOW.name,
        "workflow_id": workflow.get("id"),
        "workflow_version": workflow.get("version"),
        "frontend_version": workflow.get("extra", {}).get("frontendVersion"),
        "node_count": len(workflow["nodes"]),
        "link_count": len(workflow["links"]),
        "notes": (
            "Reference only. The native YuE2 runtime is the primary backend; entries whose "
            "native.supported is false exist in the ComfyUI graph and have no native equivalent."
        ),
        "nodes": sorted(
            (
                {
                    "id": node["id"],
                    "type": node["type"],
                    "title": node["title"],
                    "bypassed": node["bypassed"],
                    "widgets": node["widgets"],
                }
                for node in nodes.values()
            ),
            key=lambda node: node["id"],
        ),
        "parameters": mapping,
    }
    OUTPUT.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    unmatched = [row["parameter"] for row in mapping if row["comfy_widget"] and row["workflow_value"] is None]
    print(f"wrote {OUTPUT.relative_to(REPO_ROOT)}: {len(nodes)} nodes, {len(mapping)} parameters")
    if unmatched:
        print("registry widgets missing from the workflow:", unmatched)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
