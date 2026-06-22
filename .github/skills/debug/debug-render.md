# Skill: Debug Render

## When to Use
- UI not updating
- values not showing

## Steps
1. console.log props in component
2. check conditional rendering (if (!data))
3. print JSON in UI:
   {DEBUG && <pre>{JSON.stringify(data)}</pre>}

## Goal
Verify UI is receiving correct data