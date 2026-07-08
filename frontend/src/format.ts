/** Values near zero (floating-point noise from cost math, e.g. -4.6e-12) must
 * never render as "Rs -0" -- snap anything below half a rupee to a clean 0. */
export function formatCurrency(value: number): string {
  const clean = Math.abs(value) < 0.5 ? 0 : value;
  return `Rs ${clean.toLocaleString("en-IN", { maximumFractionDigits: 0 })}`;
}

export function formatDate(iso: string): string {
  const date = new Date(iso);
  return date.toLocaleString("en-IN", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
}
