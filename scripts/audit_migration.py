from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parents[1]
FEATURES_ROOT = ROOT / "syndicate" / "features"
BLUEPRINTS_ROOT = ROOT / "syndicate" / "blueprints"
STATIC_ROOT = ROOT / "syndicate" / "static"
TEMPLATES_ROOT = ROOT / "syndicate" / "templates"

GENERIC_EMPTY_PATTERNS = (
    re.compile(r"No games(?: found| available| on this slate| scheduled)?", re.IGNORECASE),
    re.compile(r"No .* available for this date", re.IGNORECASE),
    re.compile(r"No .* rows available", re.IGNORECASE),
    re.compile(r"Failed to load", re.IGNORECASE),
)


@dataclass
class Finding:
    category: str
    path: str
    line: int | None
    summary: str
    detail: str


def repo_rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def python_files(root: Path) -> Iterable[Path]:
    return sorted(path for path in root.rglob("*.py") if path.is_file())


def iter_source_shell_assets() -> Iterable[Path]:
    for root in (STATIC_ROOT, TEMPLATES_ROOT):
        for path in sorted(root.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix not in {".js", ".html"}:
                continue
            if "cards_source" not in path.name:
                continue
            yield path


def iter_hub_templates() -> Iterable[Path]:
    for path in sorted(TEMPLATES_ROOT.rglob("hub.html")):
        if path.is_file():
            yield path


def find_hub_templates_missing_shared_shell() -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_hub_templates():
        text = read_text(path)
        has_intro = "shared/_module_intro.html" in text
        has_content_panel = "shared/_content_panel.html" in text
        if has_intro and has_content_panel:
            continue
        findings.append(
            Finding(
                category="hub_template_missing_shared_shell",
                path=repo_rel(path),
                line=None,
                summary="Hub template does not use the shared intro/content shell.",
                detail="Use `shared/_module_intro.html` and at least one `shared/_content_panel.html` include so module hubs keep the same visual structure.",
            )
        )
    return findings


def function_segment(path: Path, function_name: str) -> tuple[str, int] | None:
    source = read_text(path)
    module = ast.parse(source)
    for node in module.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            start = node.lineno - 1
            end = getattr(node, "end_lineno", node.lineno)
            lines = source.splitlines()
            return "\n".join(lines[start:end]), node.lineno
    return None


def primary_hrefs_by_slug() -> dict[str, str]:
    path = ROOT / "syndicate" / "app.py"
    source = read_text(path)
    module = ast.parse(source)
    mapping: dict[str, str] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "setdefault":
            continue
        if len(node.args) < 2:
            continue
        key_node = node.args[0]
        if not isinstance(key_node, ast.Constant) or key_node.value != "SYNDICATE_SPORTS":
            continue
        sports_node = node.args[1]
        if not isinstance(sports_node, ast.List):
            continue
        for entry in sports_node.elts:
            if not isinstance(entry, ast.Dict):
                continue
            slug = None
            primary_href = None
            for key, value in zip(entry.keys, entry.values):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                    continue
                if key.value == "slug" and isinstance(value, ast.Constant) and isinstance(value.value, str):
                    slug = value.value
                if key.value == "primary_href" and isinstance(value, ast.Constant) and isinstance(value.value, str):
                    primary_href = value.value
            if slug and primary_href:
                mapping[slug] = primary_href
        break
    return mapping


def find_cards_builders_missing_empty_state() -> list[Finding]:
    findings: list[Finding] = []
    for path in python_files(FEATURES_ROOT):
        segment = function_segment(path, "build_cards_page_context")
        if segment is None:
            continue
        body, lineno = segment
        if "source_title" not in body:
            continue
        if "empty_state" in body:
            continue
        findings.append(
            Finding(
                category="cards_builder_missing_empty_state",
                path=repo_rel(path),
                line=lineno,
                summary="Cards page context defines source metadata without an explicit empty state.",
                detail="Add a module-specific `empty_state` so empty artifact dates render server truth instead of generic client copy.",
            )
        )
    return findings


def find_source_clients_with_generic_empty_copy() -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_source_shell_assets():
        text = read_text(path)
        lines = text.splitlines()
        references_empty_state = "empty_state" in text or "emptyState" in text
        if references_empty_state:
            continue
        for index, line in enumerate(lines, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            matched = next((pattern for pattern in GENERIC_EMPTY_PATTERNS if pattern.search(stripped)), None)
            if matched is None:
                continue
            findings.append(
                Finding(
                    category="source_client_generic_empty_copy",
                    path=repo_rel(path),
                    line=index,
                    summary="Source-style client still contains generic empty or unavailable copy.",
                    detail="This shell does not appear to consume server empty-state metadata yet.",
                )
            )
            break
    return findings


def find_source_routes() -> list[Finding]:
    findings: list[Finding] = []
    route_pattern = re.compile(r"render_template\((?:\"|')([^\"']*cards_source\.html)(?:\"|')")
    script_pattern = re.compile(r"cards_script\"]\s*=\s*(?:\"|')([^\"']*cards_source\.js)(?:\"|')")
    for path in python_files(BLUEPRINTS_ROOT):
        lines = read_text(path).splitlines()
        for index, line in enumerate(lines, start=1):
            match = route_pattern.search(line) or script_pattern.search(line)
            if match is None:
                continue
            findings.append(
                Finding(
                    category="source_shell_route",
                    path=repo_rel(path),
                    line=index,
                    summary=f"Source shell route points at {match.group(1)}.",
                    detail="Use these routes as the primary client-parity audit surface.",
                )
            )
    return findings


def find_hub_loops_using_global_launch_context() -> list[Finding]:
    findings: list[Finding] = []
    loop_start_pattern = re.compile(r"\{\%\s*for\s+.+\s+in\s+.+\s*\%\}")
    loop_end_pattern = re.compile(r"\{\%\s*endfor\s*\%\}")
    risky_tokens = ("launch_season", "launch_date", "season_launch_date", "latest_date")
    for path in iter_hub_templates():
        lines = read_text(path).splitlines()
        in_loop = False
        loop_start_line = 0
        for index, line in enumerate(lines, start=1):
            stripped = line.strip()
            if loop_start_pattern.search(stripped):
                in_loop = True
                loop_start_line = index
                continue
            if in_loop and loop_end_pattern.search(stripped):
                in_loop = False
                loop_start_line = 0
                continue
            if not in_loop:
                continue
            if "/season/{{" not in stripped and "?date={{" not in stripped:
                continue
            token = next((value for value in risky_tokens if value in stripped), None)
            if token is None:
                continue
            findings.append(
                Finding(
                    category="hub_loop_uses_global_launch_context",
                    path=repo_rel(path),
                    line=index,
                    summary="Hub template uses global launch context inside a per-date historical loop.",
                    detail=(
                        f"This loop appears to build per-date historical links with `{token}` instead of row-specific state. "
                        f"Review the loop that starts near line {loop_start_line}."
                    ),
                )
            )
            break
    return findings


def find_hub_intro_action_mismatches() -> list[Finding]:
    findings: list[Finding] = []
    primary_by_slug = primary_hrefs_by_slug()
    route_label_pattern = re.compile(r"route_label='/(?P<slug>[^']+)'.*action_href='(?P<href>[^']+)'", re.IGNORECASE)
    for path in iter_hub_templates():
        lines = read_text(path).splitlines()
        for index, line in enumerate(lines, start=1):
            match = route_label_pattern.search(line)
            if match is None:
                continue
            slug = str(match.group("slug") or "").strip()
            href = str(match.group("href") or "").strip()
            expected = primary_by_slug.get(slug)
            if not slug or not href or not expected:
                continue
            if expected == f"/{slug}":
                continue
            if href.startswith(expected):
                continue
            findings.append(
                Finding(
                    category="hub_intro_action_mismatch",
                    path=repo_rel(path),
                    line=index,
                    summary="Hub intro action does not match the module's declared primary href.",
                    detail=f"Expected a launch path beginning with `{expected}` for `/{slug}`, but found `{href}`.",
                )
            )
            break
    return findings


def build_findings() -> list[Finding]:
    findings: list[Finding] = []
    findings.extend(find_source_routes())
    findings.extend(find_hub_templates_missing_shared_shell())
    findings.extend(find_hub_intro_action_mismatches())
    findings.extend(find_hub_loops_using_global_launch_context())
    findings.extend(find_cards_builders_missing_empty_state())
    findings.extend(find_source_clients_with_generic_empty_copy())
    return findings


def render_markdown(findings: list[Finding]) -> str:
    by_category: dict[str, list[Finding]] = {}
    for finding in findings:
        by_category.setdefault(finding.category, []).append(finding)

    lines = ["# Migration Audit", "", f"Findings: {len(findings)}", ""]
    for category in sorted(by_category):
        entries = by_category[category]
        lines.append(f"## {category}")
        lines.append("")
        for entry in entries:
            location = entry.path if entry.line is None else f"{entry.path}:{entry.line}"
            lines.append(f"- {location}: {entry.summary} {entry.detail}")
        lines.append("")
    if not findings:
        lines.append("No findings.")
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Audit Syndicate migration parity gaps.")
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--write", type=Path, help="Optional output path for the generated report.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    findings = build_findings()

    if args.format == "json":
        output = json.dumps([asdict(finding) for finding in findings], indent=2) + "\n"
    else:
        output = render_markdown(findings)

    if args.write:
        output_path = args.write if args.write.is_absolute() else ROOT / args.write
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())