from __future__ import annotations

from typing import Sequence

from syndicate.features.football.sim_engine.smartsim2.calibration.simulator_evaluator import SimulatorEvaluation


def _format_percentage(value: float) -> str:
    return f"{value * 100:.1f}%"


def _format_value(value: float, unit: str) -> str:
    if unit == "rate":
        return _format_percentage(value)
    if unit in {"plays", "seconds", "yards", "points", "possessions"}:
        return f"{value:.2f}" if unit != "seconds" else f"{value:.1f}"
    return f"{value:.2f}"


def _metric_row(metric) -> str:
    return (
        f"| {metric.name} | {_format_value(metric.benchmark_value, metric.unit)} | "
        f"{_format_value(metric.simulated_value, metric.unit)} | {metric.error:+.3f} | "
        f"{metric.absolute_error:.3f} |"
    )


def generate_calibration_report(evaluation: SimulatorEvaluation, *, title: str = "SmartSim 2.0 Calibration Report") -> str:
    lines: list[str] = []
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"- Source: {evaluation.benchmark_snapshot.source_name}")
    lines.append(f"- Split: {evaluation.benchmark_snapshot.split.value}")
    lines.append(f"- Score: {evaluation.score:.3f}")
    lines.append(f"- Drives: {evaluation.benchmark_summary.sample_size}")
    lines.append(f"- Notes: {', '.join(evaluation.notes) if evaluation.notes else 'None'}")
    lines.append("")
    lines.append("## Target Metrics")
    lines.append("")
    lines.append("| Metric | Benchmark | Simulated | Error | Absolute Error |")
    lines.append("| --- | --- | --- | --- | --- |")
    for metric in evaluation.metric_results:
        lines.append(_metric_row(metric))
    lines.append("")
    lines.append("## Interpretation")
    lines.append("")
    lines.append("- Lower error means the simulator is closer to historical football shape.")
    lines.append("- Drive length and possessions per game should stabilize before scoring and totals are trusted.")
    lines.append("- Quarter scoring and game totals should be read as aggregate checks after the drive layer is aligned.")
    return "\n".join(lines)


__all__ = ["generate_calibration_report"]
