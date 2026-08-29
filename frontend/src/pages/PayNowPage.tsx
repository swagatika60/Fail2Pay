import { useEffect, useState } from "react"
import { useParams, Link } from "react-router-dom"
import { simulateCustomerMessage } from "../services/operations"

export default function PayNowPage() {
  const { caseId } = useParams<{ caseId: string }>()
  const [status, setStatus] = useState<"processing" | "done" | "error">(
    "processing",
  )
  const [message, setMessage] = useState<string>("")
  const [recovered, setRecovered] = useState(false)

  useEffect(() => {
    if (!caseId) {
      setStatus("error")
      setMessage("Invalid payment link.")
      return
    }
    // A customer visiting the payment link = they intend to pay now.
    simulateCustomerMessage(caseId, "pay_link")
      .then((res) => {
        setRecovered(!!res.recovered)
        setMessage(
          res.reply_text ||
            (res.recovered
              ? "Your payment has been marked as received. Thank you!"
              : "We could not process this payment. Please contact support."),
        )
        setStatus("done")
      })
      .catch(() => {
        setMessage("We could not process this payment right now.")
        setStatus("error")
      })
  }, [caseId])

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950 p-4">
      <div className="w-full max-w-md rounded-2xl border border-slate-800 bg-slate-900 p-8 text-center">
        {status === "processing" && (
          <>
            <div className="mx-auto mb-4 h-10 w-10 animate-spin rounded-full border-2 border-slate-600 border-t-blue-500" />
            <p className="text-sm text-slate-400">Processing payment…</p>
          </>
        )}

        {status === "done" && (
          <>
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-emerald-500/20 text-3xl">
              {recovered ? "✅" : "⚠️"}
            </div>
            <h1 className="text-xl font-bold text-slate-100">
              {recovered ? "Payment Received" : "Payment Not Processed"}
            </h1>
            <p className="mt-3 text-sm text-slate-400">{message}</p>
            <Link
              to="/dashboard"
              className="mt-6 inline-block rounded-lg bg-slate-800 px-5 py-2 text-sm text-slate-200 hover:bg-slate-700"
            >
              ← Back to Fail2Pay
            </Link>
          </>
        )}

        {status === "error" && (
          <>
            <div className="mx-auto mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-red-500/20 text-3xl">
              🚫
            </div>
            <h1 className="text-xl font-bold text-red-400">Payment Failed</h1>
            <p className="mt-3 text-sm text-slate-400">{message}</p>
            <Link
              to="/dashboard"
              className="mt-6 inline-block rounded-lg bg-slate-800 px-5 py-2 text-sm text-slate-200 hover:bg-slate-700"
            >
              ← Back to Fail2Pay
            </Link>
          </>
        )}
      </div>
    </div>
  )
}
