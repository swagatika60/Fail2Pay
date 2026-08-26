import type { BackendStatus } from "../types/health"

interface HealthResponse {
  status: string
  service: string
}

export async function fetchBackendStatus(): Promise<BackendStatus> {
  try {
    const response = await fetch("/api/health")
    if (!response.ok) return "offline"
    const data = (await response.json()) as HealthResponse
    return data.status === "ok" ? "connected" : "offline"
  } catch {
    return "offline"
  }
}
