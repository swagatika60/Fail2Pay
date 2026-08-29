import type { RecoverySettings, RecoverySettingsUpdate } from "../types/settings"

const TTL_MS = 1000 * 60 * 5
let settingsCache: RecoverySettings | null = null
let settingsFetchedAt = 0

export async function fetchRecoverySettings(bypass = false): Promise<RecoverySettings> {
  if (
    !bypass &&
    settingsCache &&
    Date.now() - settingsFetchedAt < TTL_MS
  ) {
    return settingsCache
  }
  const response = await fetch("/api/settings/recovery")
  if (!response.ok) throw new Error("Failed to fetch recovery settings")
  settingsCache = (await response.json()) as RecoverySettings
  settingsFetchedAt = Date.now()
  return settingsCache
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
  settingsCache = (await response.json()) as RecoverySettings
  settingsFetchedAt = Date.now()
  return settingsCache
}