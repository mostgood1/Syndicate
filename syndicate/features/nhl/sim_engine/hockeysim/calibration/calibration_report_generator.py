"""Render a human-readable calibration report (markdown) from an evaluation + overrides."""
from __future__ import annotations

from typing import Any, Dict, Optional

from .simulator_evaluator import EvaluationResult


def render_calibration_report(
    *,
    title: str,
    truth: Dict[str, Any],
    before: EvaluationResult,
    after: Optional[EvaluationResult] = None,
    overrides: Optional[Dict[str, Any]] = None,
) -> str:
    """Compose a markdown calibration report.

    ``truth`` is a :meth:`TruthSnapshot.to_dict` payload; ``before``/``after`` are evaluator results
    (pre- and post-override); ``overrides`` the applied profile field values.
    """
    prov = truth.get("provenance", {})
    lines = [f"# {title}", ""]
    lines.append(
        f"Truth: {prov.get('n_games', '?')} games, season {prov.get('season', '?')}, "
        f"{prov.get('date_from', '?')}..{prov.get('date_to', '?')} "
        f"(source {prov.get('source', '?')}).",
    )
    lines.append("")
    lines.append(f"**Accept score before:** {before.score:.4f}")
    if after is not None:
        lines.append(f"**Accept score after:**  {after.score:.4f}")
    lines.append("")

    def _table(result: EvaluationResult, header: str) -> None:
        lines.append(f"## {header}")
        lines.append("")
        lines.append("| metric | target | measured | norm error |")
        lines.append("|---|---|---|---|")
        for m in result.metric_scores:
            lines.append(
                f"| {m.name} | {m.target:.4f} | {m.measured:.4f} | {m.normalized_error:.3f} |"
            )
        lines.append("")

    _table(before, "Before")
    if after is not None:
        _table(after, "After")

    if overrides:
        lines.append("## Applied profile overrides")
        lines.append("")
        for k, v in overrides.items():
            lines.append(f"- `{k}` = `{v}`")
        lines.append("")
    return "\n".join(lines)
