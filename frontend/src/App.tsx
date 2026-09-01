import { lazy, Suspense } from "react"
import { BrowserRouter, Routes, Route, Navigate, useLocation } from "react-router-dom"
import { DashboardStoreProvider } from "./hooks/dashboardStore"
import AppLayout from "./components/layout/AppLayout"

const DashboardPage = lazy(() => import("./pages/DashboardPage"))
const LandingPage = lazy(() => import("./pages/LandingPage"))
const RevenueMapPage = lazy(() => import("./pages/RevenueMapPage"))
const RecoveryCasesPage = lazy(() => import("./pages/RecoveryCasesPage"))
const ConversationsPage = lazy(() => import("./pages/ConversationsPage"))
const PaymentPlansPage = lazy(() => import("./pages/PaymentPlansPage"))
const InvoicesPage = lazy(() => import("./pages/InvoicesPage"))
const AnalyticsPage = lazy(() => import("./pages/AnalyticsPage"))
const RecoveryCasePage = lazy(() => import("./pages/RecoveryCasePage"))
const SimulationPage = lazy(() => import("./pages/SimulationPage"))
const RecoverySettingsPage = lazy(() => import("./pages/RecoverySettingsPage"))
const PayNowPage = lazy(() => import("./pages/PayNowPage"))
const CheckoutAbandonmentsPage = lazy(() => import("./pages/CheckoutAbandonmentsPage"))
const SubscriptionFailuresPage = lazy(() => import("./pages/SubscriptionFailuresPage"))

const PUBLIC_PREFIXES = ["/overview", "/pay"]

function RouteFallback() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 pt-8">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-slate-600 border-t-blue-500" />
    </div>
  )
}

function AppRouter() {
  const location = useLocation()
  const isPublic =
    location.pathname === "/" ||
    PUBLIC_PREFIXES.some((p) => location.pathname.startsWith(p))

  if (isPublic) {
    return (
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/" element={<LandingPage />} />
          <Route path="/overview" element={<Navigate to="/" replace />} />
          <Route path="/pay/:caseId" element={<PayNowPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Suspense>
    )
  }

  return (
    <AppLayout>
      <Suspense fallback={<RouteFallback />}>
        <Routes>
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/revenue-map" element={<RevenueMapPage />} />
          <Route path="/cases" element={<RecoveryCasesPage />} />
          <Route path="/conversations" element={<ConversationsPage />} />
          <Route path="/plans" element={<PaymentPlansPage />} />
          <Route path="/invoices" element={<InvoicesPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/settings" element={<RecoverySettingsPage />} />
          <Route path="/case/:caseId" element={<RecoveryCasePage />} />
          <Route path="/checkout-abandonments" element={<CheckoutAbandonmentsPage />} />
          <Route path="/subscription-failures" element={<SubscriptionFailuresPage />} />
          <Route path="/simulation" element={<SimulationPage />} />
          <Route path="*" element={<Navigate to="/dashboard" replace />} />
        </Routes>
      </Suspense>
    </AppLayout>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <DashboardStoreProvider>
        <AppRouter />
      </DashboardStoreProvider>
    </BrowserRouter>
  )
}
