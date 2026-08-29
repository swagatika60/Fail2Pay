import { formatINRFull } from "./format"

/**
 * Split `totalAmount` (paise) into `count` installments.
 *
 * Uses integer division (`Math.floor(totalAmount / count)`) for the base amount
 * and distributes the exact remainder (`totalAmount % count`) across the FIRST
 * tranches (one extra paisa each). The sum of the returned amounts always equals
 * the total — no rupees/paise lost or invented.
 *
 * Mirrors backend `agent_engine.calculate_installments` so API and UI agree.
 */
export function calculateInstallments(
  totalAmount: number,
  count = 2,
): number[] {
  if (!Number.isFinite(totalAmount) || count <= 0) {
    throw new Error("count must be a positive integer")
  }
  const base = Math.floor(totalAmount / count)
  const remainder = totalAmount % count
  return Array.from({ length: count }, (_, i) => base + (i < remainder ? 1 : 0))
}

export interface SplitOption {
  id: string
  count: number
  label: string
  amounts: number[]
  amountsFormatted: string[]
}

export const SPLIT_COUNTS = [2, 4]

/** Build the dynamic "Split in N EMIs" quick-reply options for a case amount. */
export function buildSplitOptions(totalAmount: number): SplitOption[] {
  return SPLIT_COUNTS.map((count) => {
    const amounts = calculateInstallments(totalAmount, count)
    return {
      id: `split_${count}`,
      count,
      label: `Split in ${count} EMIs`,
      amounts,
      amountsFormatted: amounts.map(formatINRFull),
    }
  })
}

/** Human summary of an N-installment split, e.g. "2× ₹9,999.50". */
export function summarizeSplit(totalAmount: number, count: number): string {
  const amounts = calculateInstallments(totalAmount, count)
  if (count === 1) return formatINRFull(totalAmount)
  return `${count}× ${amounts.map(formatINRFull).join(" + ")}`
}
