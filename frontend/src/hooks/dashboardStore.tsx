import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react"
import type { RevenueMap, RevenueSummary, RecoveryCaseSummary } from "../types/analytics"
import {
  fetchRevenueMap,
  fetchRevenueSummary,
  fetchRecoveryCases,
  simulateSingleCase,
} from "../services/analytics"

const STALE_MS = 1000 * 60 * 5
const GC_MS = 1000 * 60 * 10

interface CacheEntry<T> {
  data: T
  fetchedAt: number
}

interface DashboardStoreValue {
  map: RevenueMap | null
  summary: RevenueSummary | null
  cases: RecoveryCaseSummary[]
  loading: boolean
  error: string | null
  ensureLoaded: () => Promise<void>
  invalidate: () => void
  simulatePaymentFailure: (amount: number) => Promise<string | null>
}

const DashboardStoreContext = createContext<DashboardStoreValue | null>(null)

interface InFlight {
  promise: Promise<void>
  at: number
}

const hasFresh = <T,>(entry: CacheEntry<T> | undefined): boolean =>
  !!entry && Date.now() - entry.fetchedAt < STALE_MS

export function DashboardStoreProvider({ children }: { children: ReactNode }) {
  const cacheRef = useRef<{
    map?: CacheEntry<RevenueMap>
    summary?: CacheEntry<RevenueSummary>
    cases?: CacheEntry<RecoveryCaseSummary[]>
  }>({})
  const inFlightRef = useRef<InFlight | null>(null)
  const lastGcRef = useRef(0)

  const [map, setMap] = useState<RevenueMap | null>(null)
  const [summary, setSummary] = useState<RevenueSummary | null>(null)
  const [cases, setCases] = useState<RecoveryCaseSummary[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const invalidate = useCallback(() => {
    cacheRef.current = {}
    inFlightRef.current = null
    setMap(null)
    setSummary(null)
    setCases([])
    setError(null)
  }, [])

  const ensureLoaded = useCallback(async () => {
    const now = Date.now()

    // Periodically drop expired entries (memory bound).
    if (now - lastGcRef.current > GC_MS) {
      for (const key of ["map", "summary", "cases"] as const) {
        const entry = cacheRef.current[key]
        if (entry && now - entry.fetchedAt >= STALE_MS) {
          delete cacheRef.current[key]
        }
      }
      lastGcRef.current = now
    }

    const cache = cacheRef.current
    const needMap = map === null && !hasFresh(cache.map)
    const needSummary = summary === null && !hasFresh(cache.summary)
    const needCases = cases.length === 0 && !hasFresh(cache.cases)

    if (!needMap && !needSummary && !needCases) return

    // Reuse whatever is already loaded rather than refetching fresh data.
    const startMap = map
    const startSummary = summary
    const startCases = cases

    if (inFlightRef.current) {
      await inFlightRef.current.promise
      return
    }

    setLoading(true)
    setError(null)

    const promise = (async () => {
      try {
        const fetches: Promise<unknown>[] = []
        if (needMap) fetches.push(fetchRevenueMap())
        if (needSummary) fetches.push(fetchRevenueSummary())
        if (needCases) fetches.push(fetchRecoveryCases())
        const results = await Promise.all(fetches)

        let idx = 0

        if (needMap) {
          const data = results[idx++] as RevenueMap
          cacheRef.current.map = { data, fetchedAt: Date.now() }
          setMap(data)
        } else if (startMap) {
          cacheRef.current.map = { data: startMap, fetchedAt: Date.now() }
        }

        if (needSummary) {
          const data = results[idx++] as RevenueSummary
          cacheRef.current.summary = { data, fetchedAt: Date.now() }
          setSummary(data)
        } else if (startSummary) {
          cacheRef.current.summary = { data: startSummary, fetchedAt: Date.now() }
        }

        if (needCases) {
          const data = results[idx++] as RecoveryCaseSummary[]
          cacheRef.current.cases = { data, fetchedAt: Date.now() }
          setCases(data)
        } else if (startCases) {
          cacheRef.current.cases = { data: startCases, fetchedAt: Date.now() }
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load dashboard data")
      } finally {
        setLoading(false)
      }
    })()

    inFlightRef.current = { promise, at: Date.now() }
    try {
      await promise
    } finally {
      inFlightRef.current = null
    }
  }, [map, summary, cases])

  // Load once on mount (shared across all pages / tab switches).
  useEffect(() => {
    ensureLoaded()
  }, [ensureLoaded])

  // Create a real persisted case via the backend API.
  // Returns the case_id so the caller can navigate to /case/{id}.
  const simulatePaymentFailure = useCallback(async (amount: number) => {
    try {
      const result = await simulateSingleCase({ amount })
      // Refresh the cases list so the new case appears immediately
      const freshCases = await fetchRecoveryCases()
      cacheRef.current.cases = { data: freshCases, fetchedAt: Date.now() }
      setCases(freshCases)
      // Refresh revenue map + summary to reflect the new at-risk revenue
      const [freshMap, freshSummary] = await Promise.all([
        fetchRevenueMap(),
        fetchRevenueSummary(),
      ])
      cacheRef.current.map = { data: freshMap, fetchedAt: Date.now() }
      cacheRef.current.summary = { data: freshSummary, fetchedAt: Date.now() }
      setMap(freshMap)
      setSummary(freshSummary)
      return result.case_id
    } catch (err) {
      console.error("[Dashboard] Failed to create simulated case:", err)
      // Fallback: if backend is unreachable, add a client-side mock so
      // the UI at least shows something. The mock won't survive a
      // refresh — but it's better than nothing.
      const names = [
        "Rahul Verma",
        "Priya Nair",
        "Amit Sharma",
        "Sneha Reddy",
        "Karan Mehta",
        "Ananya Iyer",
        "Vikram Singh",
        "Divya Patel",
      ]
      const customerName = names[Math.floor(Math.random() * names.length)]
      const now = new Date()
      const id =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `mock-webhook-${Date.now()}`
      const mockCase: RecoveryCaseSummary = {
        id,
        customer_name: customerName,
        customer_email: null,
        original_amount: amount,
        risk_level: "HIGH",
        status: "AT_RISK",
        recovered_amount: 0,
        remaining_amount: amount,
        attempt_count: 0,
        created_at: now.toISOString(),
        updated_at: now.toISOString(),
      }
      setCases((prev) => [mockCase, ...prev])
      setMap((prev) =>
        prev ? { ...prev, at_risk_revenue: prev.at_risk_revenue + amount } : prev,
      )
      setSummary((prev) =>
        prev
          ? { ...prev, revenue_at_risk: prev.revenue_at_risk + amount }
          : prev,
      )
      return null
    }
  }, [])

  const value = useMemo<DashboardStoreValue>(
    () => ({ map, summary, cases, loading, error, ensureLoaded, invalidate, simulatePaymentFailure }),
    [map, summary, cases, loading, error, ensureLoaded, invalidate, simulatePaymentFailure],
  )

  return (
    <DashboardStoreContext.Provider value={value}>
      {children}
    </DashboardStoreContext.Provider>
  )
}

export function useDashboardStore(): DashboardStoreValue {
  const ctx = useContext(DashboardStoreContext)
  if (!ctx) {
    throw new Error("useDashboardStore must be used within DashboardStoreProvider")
  }
  return ctx
}
