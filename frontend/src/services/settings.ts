import type { RecoverySettings, RecoverySettingsUpdate } from "../types/settings"

export async function fetchRecoverySettings(): Promise<RecoverySettings> {
  const response = await fetch("/api/settings/recovery")
  if (!response.ok) throw new Error("Failed to fetch recovery settings")
  return response.json()
}

export async function saveRecoverySettings(
  payload: RecoverySettingsUpdate,
): Promise<RecoverySettings> {
  const response = await fetch("/api/settings/recovery", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail =
      body?.detail?.[0]?.msg ?? body?.detail ?? "Failed to save recovery settings"
    throw new Error(String(detail))
  }
  return response.json()
}