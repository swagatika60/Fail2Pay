import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import type { InvoiceListItem } from "../types/operations"
import { fetchInvoicesList } from "../services/operations"
import { PageHeader } from "../components/ui/PageHeader"
import { Card } from "../components/ui/Card"
import { EmptyState } from "../components/ui/EmptyState"
import { StatusBadge } from "../components/ui/Badge"
import { SkeletonTable } from "../components/ui/Skeleton"
import { INVOICE_STATUS_META } from "../lib/status"
import { formatINR, formatDateTime, initials } from "../lib/format"

export default function InvoicesPage() {
  const [invoices, setInvoices] = useState<InvoiceListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<string>("all")
  const [copiedId, setCopiedId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchInvoicesList()
      .then((data) => {
        if (!cancelled) setInvoices(data)
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Failed to load invoices")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    return invoices
      .filter((i) => (status === "all" ? true : i.status === status))
      .slice()
      .sort((a, b) => Date.parse(b.created_at ?? "0") - Date.parse(a.created_at ?? "0"))
  }, [invoices, status])

  const statusTabs = useMemo(() => {
    const counts: Record<string, number> = { all: invoices.length }
    for (const i of invoices) counts[i.status] = (counts[i.status] ?? 0) + 1
    return [
      { key: "all", label: "All", count: counts.all ?? 0 },
      { key: "ISSUED", label: "Issued", count: counts.ISSUED ?? 0 },
      { key: "PAID", label: "Paid", count: counts.PAID ?? 0 },
      { key: "EXPIRED", label: "Expired", count: counts.EXPIRED ?? 0 },
      { key: "CANCELLED", label: "Cancelled", count: counts.CANCELLED ?? 0 },
    ]
  }, [invoices])

  const totalIssued = invoices.filter((i) => i.status !== "PAID").reduce((s, i) => s + i.amount, 0)
  const totalPaid = invoices.filter((i) => i.status === "PAID").reduce((s, i) => s + i.amount, 0)
  const viewedCount = invoices.filter((i) => i.viewed_at && i.status !== "PAID").length

  async function copyLink(invoice: InvoiceListItem) {
    const link = `${window.location.origin}/api/invoices/access/${invoice.secure_token}`
    try {
      await navigator.clipboard.writeText(link)
      setCopiedId(invoice.id)
      setTimeout(() => setCopiedId(null), 2000)
    } catch {
      window.prompt("Copy the invoice link:", link)
    }
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Invoices"
        subtitle={`${invoices.length} invoices · ${formatINR(totalPaid)} paid · ${formatINR(totalIssued)} outstanding across ${viewedCount} viewed`}
      />

      <div className="flex flex-wrap gap-1.5">
        {statusTabs.map((tab) => (
          <button
            key={tab.key}
            onClick={() => setStatus(tab.key)}
            className={`rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${
              status === tab.key
                ? "border-blue-500/40 bg-blue-600/15 text-blue-400"
                : "border-slate-800 bg-slate-900 text-slate-400 hover:text-slate-300"
            }`}
          >
            {tab.label} <span className="ml-1 opacity-70">{tab.count}</span>
          </button>
        ))}
      </div>

      <Card className="overflow-hidden">
        {loading ? (
          <div className="p-6">
            <SkeletonTable rows={7} />
          </div>
        ) : error ? (
          <div className="p-6 text-center text-red-400">{error}</div>
        ) : filtered.length === 0 ? (
          <div className="p-6">
            <EmptyState
              icon="🧾"
              title="No invoices yet"
              description="Invoices created for customer payment requests appear here."
            />
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead>
                <tr className="border-b border-slate-800 text-xs uppercase tracking-wide text-slate-500">
                  <th className="px-4 py-3 font-medium">Invoice</th>
                  <th className="px-4 py-3 font-medium">Customer</th>
                  <th className="px-4 py-3 font-medium">Amount</th>
                  <th className="px-4 py-3 font-medium">Status</th>
                  <th className="px-4 py-3 font-medium">Issued</th>
                  <th className="px-4 py-3 font-medium">Viewed</th>
                  <th className="px-4 py-3 font-medium">Delivered</th>
                  <th className="px-4 py-3 text-right font-medium">Action</th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((inv) => {
                  const meta = INVOICE_STATUS_META[inv.status] ?? {
                    label: inv.status,
                    badge: "bg-slate-700/40 text-slate-300 border-slate-600/40",
                    dot: "bg-slate-400",
                    text: "text-slate-300",
                  }
                  return (
                    <tr
                      key={inv.id}
                      className="border-b border-slate-800/50 transition-colors last:border-0 hover:bg-slate-800/40"
                    >
                      <td className="px-4 py-3">
                        <span className="font-mono text-xs font-medium text-slate-300">
                          {inv.invoice_number}
                        </span>
                        {inv.description && (
                          <span className="block max-w-[180px] truncate text-xs text-slate-500">
                            {inv.description}
                          </span>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-slate-700 text-[10px] font-bold text-slate-200">
                            {initials(inv.customer_name)}
                          </span>
                          <div className="min-w-0">
                            <div className="truncate font-medium text-slate-200">
                              {inv.customer_name || "Unknown customer"}
                            </div>
                            {inv.customer_email && (
                              <div className="truncate text-xs text-slate-500">
                                {inv.customer_email}
                              </div>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 font-semibold text-slate-200">
                        {formatINR(inv.amount)}
                      </td>
                      <td className="px-4 py-3">
                        <StatusBadge meta={meta} />
                      </td>
                      <td className="px-4 py-3 text-slate-500">
                        {formatDateTime(inv.issued_at ?? inv.created_at)}
                      </td>
                      <td className="px-4 py-3 text-slate-500">
                        {inv.viewed_at ? (
                          <>
                            {formatDateTime(inv.viewed_at)}
                            {inv.access_count > 1 && (
                              <span className="ml-1 text-xs text-slate-600">
                                ×{inv.access_count}
                              </span>
                            )}
                          </>
                        ) : (
                          "Not yet"
                        )}
                      </td>
                      <td className="px-4 py-3 text-slate-500">
                        {inv.delivered_via ? (
                          <>
                            <span className="capitalize">{inv.delivered_via}</span>
                            {inv.delivered_at && (
                              <span className="block text-xs text-slate-600">
                                {formatDateTime(inv.delivered_at)}
                              </span>
                            )}
                          </>
                        ) : (
                          "—"
                        )}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2">
                          {inv.case_id && (
                            <Link
                              to={`/case/${inv.case_id}`}
                              className="text-xs font-medium text-blue-400 hover:text-blue-300"
                            >
                              Case
                            </Link>
                          )}
                          <button
                            onClick={() => copyLink(inv)}
                            className="rounded-lg bg-slate-800 px-2.5 py-1.5 text-xs font-medium text-slate-200 transition-colors hover:bg-slate-700"
                          >
                            {copiedId === inv.id ? "Copied!" : "Copy link"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  )
}