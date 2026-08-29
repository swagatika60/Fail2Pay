import { useEffect, useState, type ReactNode } from "react"
import { Link, useLocation } from "react-router-dom"
import { fetchBackendStatus } from "../../services/health"
import { useDashboardStore } from "../../hooks/dashboardStore"
import type { BackendStatus } from "../../types/health"

const STATUS_META: Record<BackendStatus, { label: string; dot: string }> = {
  checking: { label: "Connecting…", dot: "bg-amber-400" },
  connected: { label: "Backend online", dot: "bg-green-400" },
  offline: { label: "Backend offline", dot: "bg-red-500" },
}

interface NavItem {
  to: string
  label: string
  icon: ReactNode
  match: (path: string) => boolean
  prefetch?: () => Promise<unknown>
}

function Icon({ d, className = "" }: { d: string; className?: string }) {
  return (
    <svg
      className={`h-4.5 w-4.5 ${className}`}
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth={1.8}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      <path d={d} />
    </svg>
  )
}

const NAV_ITEMS: NavItem[] = [
  {
    to: "/dashboard",
    label: "Dashboard",
    match: (p) => p === "/dashboard",
    icon: <Icon d="M3 3h7v7H3zM14 3h7v4h-7zM14 11h7v10h-7zM3 14h7v7H3z" />,
    prefetch: () => import("../../pages/DashboardPage"),
  },
  {
    to: "/revenue-map",
    label: "Revenue Map",
    match: (p) => p.startsWith("/revenue-map"),
    icon: (
      <Icon d="M3 17l6-6 4 4 8-8M3 21h18M3 3v18" />
    ),
    prefetch: () => import("../../pages/RevenueMapPage"),
  },
  {
    to: "/cases",
    label: "Recovery Cases",
    match: (p) => p.startsWith("/cases") || p.startsWith("/case/"),
    icon: (
      <Icon d="M3 7l9-4 9 4-9 4-9-4zM3 7v10l9 4 9-4V7M12 11v10" />
    ),
    prefetch: () => import("../../pages/RecoveryCasesPage"),
  },
  {
    to: "/conversations",
    label: "Conversations",
    match: (p) => p.startsWith("/conversations"),
    icon: <Icon d="M21 11.5a8.5 8.5 0 01-8.5 8.5c-1.5 0-2.9-.4-4.1-1L3 21l2-5.4a8.5 8.5 0 1116-4.1z" />,
    prefetch: () => import("../../pages/ConversationsPage"),
  },
  {
    to: "/plans",
    label: "Payment Plans",
    match: (p) => p.startsWith("/plans"),
    icon: (
      <Icon d="M8 3v18M16 3v18M3 8h18M3 16h18M6 3h12a1 1 0 011 1v16a1 1 0 01-1 1H6a1 1 0 01-1-1V4a1 1 0 011-1z" />
    ),
    prefetch: () => import("../../pages/PaymentPlansPage"),
  },
  {
    to: "/invoices",
    label: "Invoices",
    match: (p) => p.startsWith("/invoices"),
    icon: (
      <Icon d="M14 3H6a1 1 0 00-1 1v16a1 1 0 001 1h12a1 1 0 001-1V8l-5-5zM14 3v5h5M9 13h6M9 17h6" />
    ),
    prefetch: () => import("../../pages/InvoicesPage"),
  },
  {
    to: "/analytics",
    label: "Analytics",
    match: (p) => p.startsWith("/analytics"),
    icon: (
      <Icon d="M4 20V10M10 20V4M16 20v-7M21 20H3" />
    ),
    prefetch: () => import("../../pages/AnalyticsPage"),
  },
  {
    to: "/settings",
    label: "Settings",
    match: (p) => p.startsWith("/settings"),
    icon: (
      <Icon d="M12 15a3 3 0 100-6 3 3 0 000 6zM12 3v2.2M12 18.8V21M5.6 5.6l1.6 1.6M16.8 16.8l1.6 1.6M3 12h2.2M18.8 12H21M5.6 18.4l1.6-1.6M16.8 7.2l1.6-1.6" />
    ),
    prefetch: () => import("../../pages/RecoverySettingsPage"),
  },
]

function Brand() {
  return (
    <Link to="/" className="flex items-center gap-3 px-1">
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-blue-600 text-base font-black text-white">
        F
      </span>
      <span>
        <span className="block text-sm font-bold tracking-tight text-slate-100">
          Fail2Pay
        </span>
        <span className="block text-[11px] text-slate-500">
          Revenue Recovery
        </span>
      </span>
    </Link>
  )
}

export default function AppLayout({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<BackendStatus>("checking")
  const [drawerOpen, setDrawerOpen] = useState(false)
  const location = useLocation()
  const { ensureLoaded } = useDashboardStore()

  useEffect(() => {
    let cancelled = false
    async function check() {
      const result = await fetchBackendStatus()
      if (!cancelled) setStatus(result)
    }
    check()
    const interval = setInterval(check, 15000)
    return () => {
      cancelled = true
      clearInterval(interval)
    }
  }, [])

  useEffect(() => {
    setDrawerOpen(false)
  }, [location.pathname])

  const meta = STATUS_META[status]

  const nav = (
    <nav className="flex flex-col gap-0.5">
      {NAV_ITEMS.map((item) => {
        const active = item.match(location.pathname)
        const onPrefetch = () => {
          if (item.prefetch) item.prefetch()
          if (item.to === "/dashboard" || item.to === "/revenue-map" || item.to === "/cases") {
            ensureLoaded()
          }
        }
        return (
          <Link
            key={item.to}
            to={item.to}
            onMouseEnter={onPrefetch}
            onFocus={onPrefetch}
            className={`flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors ${
              active
                ? "bg-blue-600/15 text-blue-400"
                : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-200"
            }`}
          >
            <span
              className={`${active ? "text-blue-400" : "text-slate-500"}`}
            >
              {item.icon}
            </span>
            {item.label}
            {active && (
              <span className="ml-auto h-1.5 w-1.5 rounded-full bg-blue-400" />
            )}
          </Link>
        )
      })}
    </nav>
  )

  const sidebarFooter = (
    <div className="border-t border-slate-800 px-3 pt-4">
      <div className="flex items-center gap-2 rounded-lg bg-slate-900 px-3 py-2">
        <span className={`h-2 w-2 shrink-0 rounded-full ${meta.dot}`} />
        <span className="truncate text-xs font-medium text-slate-400">
          {meta.label}
        </span>
      </div>
      <Link
        to="/simulation"
        className="mt-2 flex items-center gap-2 rounded-lg px-3 py-2 text-xs font-medium text-slate-500 transition-colors hover:bg-slate-800/60 hover:text-slate-300"
      >
        <Icon d="M12 9v2m0 4h.01M12 6a7 7 0 100 14 7 7 0 000-14zM5.6 4.6 4.5 3.5M18.4 4.6l1.1-1.1" />
        Developer tools
      </Link>
    </div>
  )

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      {/* Desktop sidebar */}
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 flex-col border-r border-slate-800 bg-slate-950 lg:flex">
        <div className="border-b border-slate-800 px-4 py-5">
          <Brand />
        </div>
        <div className="flex-1 overflow-y-auto px-3 py-4">{nav}</div>
        {sidebarFooter}
      </aside>

      {/* Mobile header */}
      <header className="sticky top-0 z-30 flex items-center justify-between border-b border-slate-800 bg-slate-950/95 px-4 py-3 backdrop-blur lg:hidden">
        <Brand />
        <button
          onClick={() => setDrawerOpen(!drawerOpen)}
          aria-label="Toggle navigation"
          className="rounded-lg p-2 text-slate-400 hover:bg-slate-800"
        >
          <svg
            className="h-5 w-5"
            fill="none"
            viewBox="0 0 24 24"
            stroke="currentColor"
            strokeWidth={1.8}
          >
            {drawerOpen ? (
              <path strokeLinecap="round" d="M6 6l12 12M6 18L18 6" />
            ) : (
              <path strokeLinecap="round" d="M4 7h16M4 12h16M4 17h16" />
            )}
          </svg>
        </button>
      </header>

      {/* Mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setDrawerOpen(false)}
          />
          <div className="absolute inset-y-0 left-0 flex w-64 flex-col bg-slate-950 shadow-2xl">
            <div className="border-b border-slate-800 px-4 py-5">
              <Brand />
            </div>
            <div className="flex-1 overflow-y-auto px-3 py-4">{nav}</div>
            {sidebarFooter}
          </div>
        </div>
      )}

      {/* Content */}
      <div className="px-4 py-6 sm:px-6 lg:ml-60 lg:px-8">
        <main className="mx-auto max-w-7xl">{children}</main>
      </div>
    </div>
  )
}