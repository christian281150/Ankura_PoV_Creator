/** Formatting helpers. All monetary values arrive in EUR; scaling happens here only. */

export function eurM(v: number, digits = 1): string {
  return `${(v / 1_000_000).toFixed(digits)}`;
}

export function pct(v: number, digits = 1): string {
  const s = (v * 100).toFixed(digits);
  return `${v > 0 ? '+' : ''}${s}%`;
}

export function score(v: number): string {
  return v.toFixed(2).replace(/^0/, '');
}

/** Fiscal year keyed by end year: 2025 = 1 May 2024 – 30 Apr 2025. */
export function fyLabel(fy: number): string {
  return `FY${String(fy).slice(2)}`;
}

export function cn(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(' ');
}
