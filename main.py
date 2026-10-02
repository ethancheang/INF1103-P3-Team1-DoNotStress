"""Temporary CLI front end for the base four-layer pipeline.

Pipeline: User → io_manager → ai_manager → logic_manager → data_manager
Replace this with Flask later; keep orchestration thin and out of the managers.
"""

from __future__ import annotations

import ai_manager
import data_manager
import io_manager
import logic_manager


def _confirm_save() -> bool:
    """Ask yes/no using io_manager's validator (temporary; no Flask yet)."""
    while True:
        raw = input("Save this record? (yes/no): ")
        ok, value = io_manager.validate_financial_stress(raw)
        if ok:
            return bool(value)
        io_manager.print_error(value)


def run_checkin() -> None:
    io_manager.print_message("DoNotStress — temporary CLI check-in")
    io_manager.print_message("")

    record = io_manager.collect_student_record()
    io_manager.print_message("")
    io_manager.print_student_record(record)

    io_manager.print_message("")
    io_manager.print_message("Running AI analysis (needs GEMINI_API_KEY)...")
    ok, enriched, error = ai_manager.analyse_student(record)
    if not ok or enriched is None:
        io_manager.print_error(error or "AI analysis failed.")
        io_manager.print_message("Stopped. Set GEMINI_API_KEY and try again.")
        return

    final = logic_manager.apply_intervention_tier(enriched)

    io_manager.print_message("")
    io_manager.print_message("Intervention result")
    io_manager.print_message(
        f"Tier {final.get('intervention_tier')} — {final.get('tier_label')} "
        f"({final.get('colour')})"
    )
    io_manager.print_message(f"Rule: {final.get('rule')}")
    io_manager.print_message(f"Action: {final.get('outcome')}")
    if final.get("risk_category"):
        io_manager.print_message(
            f"AI risk: {final.get('risk_category')} "
            f"(score {final.get('risk_score')})"
        )

    io_manager.print_message("")
    if not _confirm_save():
        io_manager.print_message("Not saved.")
        return

    saved = data_manager.save_record(final)
    if saved.get("ok"):
        io_manager.print_message(f"Saved to {saved.get('path')}")
    else:
        io_manager.print_error(saved.get("error") or "Could not save.")


if __name__ == "__main__":
    run_checkin()


# $env:GEMINI_API_KEY="your-key-here"   # required for this temp CLI
# python main.py
