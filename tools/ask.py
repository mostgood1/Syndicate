import os

BASE = "docs/ai_context"

def load(file):
    path = os.path.join(BASE, file)
    return open(path).read() if os.path.exists(path) else ""

def build_prompt(task):
    return f"""

SYSTEM CONTEXT:
{load("architecture.md")}

DATA FLOW CONTEXT:
{load("data_flow_system.md")}

SIMULATION CONTEXT:
{load("simulation_system.md")}

ADAPTER GAP CONTEXT:
{load("simulation_adapter_gap.md")}

DAILY PIPELINE CONTEXT:
{load("daily_pipeline.md")}

SIMULATION TIMING CONTEXT:
{load("simulation_timing.md")}

RUNTIME CONTEXT:
{load("runtime_infrastructure.md")}

EXECUTION MODEL:
{load("runtime_execution_model.md")}

DECISIONS:
{load("decisions.md")}

TASK:
{task}
"""

if __name__ == "__main__":
    import sys
    query = " ".join(sys.argv[1:])
    prompt = build_prompt(query)
    print(prompt)