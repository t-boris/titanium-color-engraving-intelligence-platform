"""Local MCP tools for LightBurn experiments, photo mapping and research evidence.

Run with ``titanium-research-mcp --data-dir ~/.titanium-platform``. It shares the
same SQLite store as the browser app; the server never operates the laser itself.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from . import application_guide, devices, research, setup as su
from .db import Store, open_store


def build_server(store: Store) -> FastMCP:
    server = FastMCP("Laser Workshop Research")

    @server.tool()
    def list_lasers() -> list[dict]:
        """List physical lasers and their currently installed lenses."""
        return devices.list_devices(store)

    @server.tool()
    def list_materials() -> list[dict]:
        """List physical material stocks, grades and batches."""
        return su.list_materials(store)

    @server.tool()
    def list_research_goals() -> list[dict]:
        """List goals such as text, lines, cleaning, color, deep engraving and cutting."""
        return application_guide.list_goals()

    @server.tool()
    def list_research_sessions() -> list[dict]:
        """List saved goal-driven experiments."""
        return research.list_sessions(store)

    @server.tool()
    def create_research_session(device_id: int, material_id: int, goal: str, target: str) -> dict:
        """Start a goal for one laser, its installed lens and one material stock."""
        return research.create_session(store, device_id, material_id, goal, target)

    @server.tool()
    def get_research_context(session_id: int) -> dict:
        """Read passport, stock, accepted findings, evidence and available compact plate types."""
        return research.context(store, session_id)

    @server.tool()
    def suggest_next_test(session_id: int) -> dict:
        """Read the evidence-based next-test suggestion without creating a file."""
        return research.next_test(store, session_id)

    @server.tool()
    def preview_lightburn_test(session_id: int, test_type: str, settings: dict | None = None) -> dict:
        """Preview a content-sized plate; small_patches makes 1–4 squares of 3–5 mm, fill_sizes 4 mm high strips of
        settings.recipes at settings.widths_mm. The size limit (default 100 mm, at most 300 mm) is a ceiling.
        settings.pulse_width (ns) is required and must be a step of the laser: no value is filled in."""
        return research.preview_plate(store, session_id, test_type, settings)

    @server.tool()
    def create_lightburn_test(session_id: int, test_type: str, settings: dict | None = None) -> dict:
        """Create a compact, validated test plate and return the LightBurn download URL; settings.pulse_width is required."""
        return research.create_plate(store, session_id, test_type, settings)

    @server.tool()
    def replace_lightburn_test(session_id: int, plan_id: int, test_type: str, settings: dict | None = None) -> dict:
        """Replace the pending plate with a new validated file, preserving the old plate in history; refuses linked photos."""
        return research.create_plate(store, session_id, test_type, settings, replace_plan_id=plan_id)

    @server.tool()
    def cancel_lightburn_test(session_id: int, plan_id: int, reason: str) -> dict:
        """Cancel the pending plate without a photo and preserve it in history."""
        return research.cancel_pending_plate(store, session_id, plan_id, reason)

    @server.tool()
    def inspect_photo_result(session_id: int, pair_id: int) -> dict:
        """Read an uploaded photo check or accepted vector-level measurements."""
        return research.inspect_pair(store, session_id, pair_id)

    @server.tool()
    def map_uploaded_photo(session_id: int, pair_id: int) -> dict:
        """Run the existing photo-to-LightBurn-vector alignment; operator review is still required."""
        return research.run_photo_mapping(store, session_id, pair_id)

    @server.tool()
    def save_research_insight(session_id: int, purpose: str, claim: str, confidence: str,
                              evidence_pair_ids: list[int]) -> dict:
        """Save an evidence-linked hypothesis or candidate from accepted photo checks."""
        return research.save_insight(store, session_id, purpose, claim, confidence, evidence_pair_ids)

    return server


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Local MCP tools for laser research")
    parser.add_argument("--data-dir", type=Path, default=Path.home() / ".titanium-platform")
    args = parser.parse_args(argv)
    store = open_store(args.data_dir, "titanium-research-mcp")
    try:
        build_server(store).run(transport="stdio")
    finally:
        store.close()


if __name__ == "__main__":
    main()
