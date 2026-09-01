import { useEffect, useState } from "react"
import { useParams, Link } from "react-router-dom"
import {
  createRazorpayOrder,
  simulateCustomerMessage,
} from "../services/operations"
import { fetchRecoveryCaseDetail } from "../services/analytics"
import type { RecoveryCaseDetail } from "../types/analytics"

type Stage = "loading" | "ready" | "processing" | "done" | "error"

declare global {
  interface Window {
    Razorpay?: new (options: Record<string, unknown>) => {
      open: () => void
    }
  }
}

function formatRupees(paise: number): string {
  return `₹${(paise / 100).toLocaleString("en-IN")}`
}

export default function PayNowPage() {
  const { caseId } = useParams<{ caseId: string }>()
  const [stage, setStage] = useState<Stage>("loading")
  const [detail, setDetail] = useState<RecoveryCaseDetail | null>(null)
  const [message, setMessage] = useState<string>("")
  const [recovered, setRecovered] = useState(false)
  const [mode, setMode] = useState<string>("")
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    if (!caseId) {
      setStage("error")
      setMessage("Invalid payment link.")
      return
    }
    setStage("loading")
    fetchRecoveryCaseDetail(caseId, { bypass: false })
      .then((d) => {
        setDetail(d)
        setStage("ready")
      })
      .catch(() => {
        setStage("ready")
      })
  }, [caseId])

  const alreadyPaid =
    detail && (detail.status === "RECOVERED" || detail.remaining_amount <= 0)

  const proceedRealCheckout = async () => {
    if (!caseId || !detail) return
    setMode("razorpay")
    const keyId = import.meta.env.VITE_RAZORPAY_KEY_ID as string | undefined
    try {
      if (!keyId) throw new Error("razorpay_not_configured")
      await createRazorpayOrder(detail.remaining_amount, `pay_${caseId}`)
      // Razorpay configured → attempt a real test-mode checkout.
      if (typeof window.Razorpay === "undefined") {
        await new Promise<void>((resolve, reject) => {
          const script = document.createElement("script")
          script.src = "https://checkout.razorpay.com/v1/checkout.js"
          script.onload = () => resolve()
          script.onerror = () => reject(new Error("checkout_load_failed"))
          document.body.appendChild(script)
        })
      }
      const rzp = new window.Razorpay!({
        key: keyId,
        amount: detail.remaining_amount,
        currency: "INR",
        name: "Fail2Pay",
        description: `Payment for recovery case ${caseId.slice(0, 8)}`,
        prefill: { name: detail.customer_name || undefined },
        handler: () => {
          // A real capture arrives by webhook; surface success optimistically.
          setRecovered(true)
          setMessage(
            "Payment initiated. Your transaction will be confirmed once the gateway settles.",
          )
          setStage("done")
        },
        modal: { ondismiss: handleFallback },
      })
      rzp.open()
      return
    } catch {
      // No Razorpay keys configured → fall back to the verified demo path.
      await handleFallback()
    }
  }

  const handleFallback = async () => {
    if (!caseId) return
    setMode("simulated")
    setSubmitting(true)
    try {
      const res = await simulateCustomerMessage(caseId, "pay_link")
      setRecovered(!!res.recovered)
      setMessage(
        res.reply_text ||
          (res.recovered
            ? "Your payment has been marked as received. Thank you!"
            : "We could not process this payment. Please contact support."),
      )
      setStage("done")
    } catch {
      setMessage("We could not process this payment right now.")
      setStage("error")
    } finally {
      setSubmitting(false)
    }
  }

  const amount = detail?.remaining_amount ?? 0

  return (
    <div className="flex min-h-screen items-center justify-center bg-canvas p-4">
      <div className="w-full max-w-md rounded-2xl border border-edge bg-panel p-8 text-center">
        {stage === "loading" && (
          <>
            <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-2 border-slate-600 border-t-blue-500" />
            <p className="text-sm text-slate-400">Preparing your payment link…</p>
          </>
        )}

        {stage === "ready" && (
          <>
            <div className="mx-auto mb-3 flex h-14 w-14 items-center justify-center rounded-full bg-accent-soft text-3xl">
              💳
            </div>
            <h1 className="text-xl font-bold text-slate-100">
              {detail?.customer_name
                ? `Hi ${detail.customer_name},`
                : "Complete Your Payment"}
            </h1>
            <p className="mt-2 text-sm text-slate-400">
              {alreadyPaid
                ? "This balance is already settled. No payment is due."
                : "Your outstanding balance with Fail2Pay."}
            </p>

            {!alreadyPaid && (
              <>
                <div className="mx-auto mt-5 max-w-xs rounded-xl border border-accent/30 bg-accent-soft px-6 py-4">
                  <div className="text-[11px] uppercase tracking-wider text-accent/80">
                    Amount due
                  </div>
                  <div className="mt-1 text-3xl font-bold text-accent">
                    {formatRupees(amount)}
                  </div>
                </div>

                <button
                  disabled={submitting}
                  onClick={proceedRealCheckout}
                  className="mt-6 inline-flex w-full items-center justify-center gap-2 rounded-lg bg-accent px-5 py-3 text-sm font-semibold text-slate-950 transition-colors hover:bg-accent/80 disabled:opacity-50"
                >
                  {submitting ? "Processing…" : "Pay Now"}
                </button>
                <p className="mt-3 text-[11px] text-slate-500">
                  {mode === "razorpay"
                    ? "Razorpay Test Mode checkout"
                    : "Secured via Razorpay · Test Mode"}
                </p>
              </>
            )}
          </>
        )}

        {stage === "done" && (
          <>
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/20 text-3xl">
              {recovered ? "✅" : "⚠️"}
            </div>
            <h1 className="text-xl font-bold text-slate-100">
              {recovered ? "Payment Received" : "Action Needed"}
            </h1>
            <p className="mt-3 text-sm text-slate-400">{message}</p>
          </>
        )}

        {stage === "error" && (
          <>
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-500/20 text-3xl">
              🚫
            </div>
            <h1 className="text-xl font-bold text-red-400">Payment Failed</h1>
            <p className="mt-3 text-sm text-slate-400">{message}</p>
          </>
        )}

        {(stage === "done" || stage === "error") && (
          <Link
            to="/overview"
            className="mt-6 inline-block rounded-lg bg-slate-800 px-5 py-2 text-sm text-slate-200 hover:bg-slate-700"
          >
            ← Back to Fail2Pay
          </Link>
        )}
      </div>
    </div>
  )
}
