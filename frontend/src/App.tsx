import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom"
import AppLayout from "./components/layout/AppLayout"
import DashboardPage from "./pages/DashboardPage"
import RevenueMapPage from "./pages/RevenueMapPage"
import RecoveryCasesPage from "./pages/RecoveryCasesPage"
import ConversationsPage from "./pages/ConversationsPage"
import PaymentPlansPage from "./pages/PaymentPlansPage"
import InvoicesPage from "./pages/InvoicesPage"
import AnalyticsPage from "./pages/AnalyticsPage"
import RecoveryCasePage from "./pages/RecoveryCasePage"
import SimulationPage from "./pages/SimulationPage"
import RecoverySettingsPage from "./pages/RecoverySettingsPage"

export default function App() {
  return (
    <BrowserRouter>
      <AppLayout>
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/revenue-map" element={<RevenueMapPage />} />
          <Route path="/cases" element={<RecoveryCasesPage />} />
          <Route path="/conversations" element={<ConversationsPage />} />
          <Route path="/plans" element={<PaymentPlansPage />} />
          <Route path="/invoices" element={<InvoicesPage />} />
          <Route path="/analytics" element={<AnalyticsPage />} />
          <Route path="/settings" element={<RecoverySettingsPage />} />
          <Route path="/case/:caseId" element={<RecoveryCasePage />} />
          <Route path="/simulation" element={<SimulationPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AppLayout>
    </BrowserRouter>
  )
}