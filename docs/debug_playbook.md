# Debug Playbook

## Flow
API → Transform → State → Props → Render

## Steps
1. Check API response
2. Check transformed data
3. Check component props
4. Validate field names
5. Check rendering conditions

## Common Issues
- undefined data
- incorrect field names
- blocked rendering condition
- API mismatch between local and production (the fleet, `http://127.0.0.1:10000`; Render is retired)