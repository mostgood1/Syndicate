from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def load(file):
    path = ROOT / file
    return path.read_text(encoding="utf-8") if path.exists() else ""

def build_prompt(task):
    return f"""

SYSTEM CONTEXT:
{load("docs/ai_context/architecture.md")}

DATA FLOW CONTEXT:
{load("docs/ai_context/data_flow_system.md")}

SIMULATION CONTEXT:
{load("docs/ai_context/simulation_system.md")}

SIMULATION ADAPTER CONTEXT:
{load("docs/ai_context/simulation_adapter_design.md")}

DAILY PIPELINE CONTEXT:
{load("docs/ai_context/daily_pipeline.md")}

DAILY UPDATE CONTROL PLANE:
{load("docs/daily_update_control_plane.md")}

SIMULATION TIMING CONTEXT:
{load("docs/ai_context/simulation_timing.md")}

RUNTIME CONTEXT:
{load("docs/ai_context/runtime_infrastructure.md")}

EXECUTION MODEL:
{load("docs/ai_context/runtime_execution_model.md")}

DECISIONS:
{load("docs/ai_context/decisions.md")}

INTELLIGENCE / BETTING BOARD ASSESSMENT:
{load("docs/intelligence_betting_board_assessment.md")}

DAILY UPDATE WORKFLOW:
{load("docs/daily_update_workflow.md")}

TASK:
{task}
"""

if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:])
    prompt = build_prompt(query)
    print(prompt)