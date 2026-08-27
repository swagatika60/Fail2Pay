import type {
  RevenueSummary,
  RecoveryCaseSummary,
  RecoveryCaseDetail,
} from "../types/analytics"

export async function fetchRevenueSummary(): Promise<RevenueSummary> {
  const response = await fetch("/api/analytics/summary")
  if (!response.ok) throw new Error("Failed to fetch revenue summary")
  return response.json()
}

export async function fetchRecoveryCases(): Promise<RecoveryCaseSummary[]> {
  const response = await fetch("/api/analytics/recovery-cases")
  if (!response.ok) throw new Error("Failed to fetch recovery cases")
  return response.json()
}

export async function fetchRecoveryCaseDetail(
  caseId: string,
): Promise<RecoveryCaseDetail> {
  const response = await fetch(`/api/analytics/recovery-cases/${caseId}`)
  if (!response.ok) throw new Error("Failed to fetch case detail")
  return response.json()
}
