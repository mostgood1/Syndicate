# Code Patterns

## Simulation Pattern
- Input: state
- Process: compute next state
- Output: updated state

## Evaluation Pattern
- Input: simulation result
- Process: compute metrics
- Output: score

## Optimization Pattern
- Avoid recomputing unchanged state
- Cache or short-circuit when possible

## File Structure Pattern
- Each file has a single responsibility
- Simulation, state, and evaluation are separated