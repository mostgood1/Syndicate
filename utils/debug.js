export function trace(label, value) {
  console.log(`[TRACE] ${label}:`, value);

  if (value === undefined) {
    console.error(`[TRACE ERROR] ${label} is undefined`);
  }

  return value;
}