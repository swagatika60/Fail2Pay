import { useEffect, useMemo, useState } from "react"
import { Link } from "react-router-dom"
import type { ConversationListItem } from "../types/operations"
import { fetchConversationsList } from "../services/operations"
import { PageHeader } from "../components/ui/PageHeader"
import { Card } from "../components/ui/Card"
import { EmptyState } from "../components/ui/EmptyState"
import { StatusBadge } from "../components/ui/Badge"
import { SkeletonTable } from "../components/ui/Skeleton"
import { caseMeta, CONVERSATION_STATUS_META } from "../lib/status"
import { timeAgo, formatDateTime, initials, truncate } from "../lib/format"
import SimulateMessageControls from "../components/dashboard/SimulateMessageControls"

export default function ConversationsPage() {
  const [conversations, setConversations] = useState<ConversationListItem[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [channel, setChannel] = useState<string>("all")
  const [query, setQuery] = useState("")
  const [openId, setOpenId] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchConversationsList()
      .then((data) => {
        if (!cancelled) setConversations(data)
      })
      .catch((err) => {
        if (!cancelled)
          setError(err instanceof Error ? err.message : "Failed to load conversations")
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  const filtered = useMemo(() => {
    return conversations
      .filter((c) => (channel === "all" ? true : c.channel === channel))
      .filter((c) => {
        if (!query.trim()) return true
        const q = query.trim().toLowerCase()
        return (
          (c.customer_name ?? "").toLowerCase().includes(q) ||
          (c.last_message?.content ?? "").toLowerCase().includes(q)
        )
      })
  }, [conversations, channel, query])

  const channelCounts = useMemo(() => {
    const m: Record<string, number> = { all: conversations.length, whatsapp: 0, email: 0 }
    for (const c of conversations) m[c.channel] = (m[c.channel] ?? 0) + 1
    return m
  }, [conversations])

  const totalInbound = conversations.reduce((s, c) => s + c.inbound_count, 0)
  const totalOutbound = conversations.reduce((s, c) => s + c.outbound_count, 0)

  const refresh = () => {
    fetchConversationsList({ bypass: true })
      .then(setConversations)
      .catch(() => {})
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Conversations"
        subtitle={`${conversations.length} threads · ${totalOutbound} outbound · ${totalInbound} customer replies`}
      />

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex items-center gap-2">
          <button
            onClick={() => setChannel("all")}
            className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
              channel === "all"
                ? "border-blue-500/40 bg-blue-600/15 text-blue-400"
                : "border-slate-800 text-slate-400 hover:text-slate-300"
            }`}
          >
            All <span className="ml-1 opacity-70">{channelCounts.all}</span>
          </button>
          <button
            onClick={() => setChannel("whatsapp")}
            className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
              channel === "whatsapp"
                ? "border-blue-500/40 bg-blue-600/15 text-blue-400"
                : "border-slate-800 text-slate-400 hover:text-slate-300"
            }`}
          >
            WhatsApp <span className="ml-1 opacity-70">{channelCounts.whatsapp ?? 0}</span>
          </button>
          <button
            onClick={() => setChannel("email")}
            className={`rounded-full border px-3 py-1.5 text-xs font-medium ${
              channel === "email"
                ? "border-blue-500/40 bg-blue-600/15 text-blue-400"
                : "border-slate-800 text-slate-400 hover:text-slate-300"
            }`}
          >
            Email <span className="ml-1 opacity-70">{channelCounts.email ?? 0}</span>
          </button>
        </div>
        <input
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search by customer or message…"
          className="w-full rounded-lg border border-slate-800 bg-slate-900 py-1.5 pl-3 pr-3 text-sm text-slate-200 placeholder:text-slate-600 sm:max-w-xs"
        />
      </div>

      {loading ? (
        <Card className="p-6">
          <SkeletonTable rows={7} />
        </Card>
      ) : error ? (
        <Card className="p-6 text-center text-red-400">{error}</Card>
      ) : filtered.length === 0 ? (
        <EmptyState
          icon="💬"
          title="No conversations yet"
          description="Customer replies to recovery messages will appear here."
        />
      ) : (
        <div className="space-y-3">
          {filtered.map((conv) => {
            const isOpen = openId === conv.id
            const convStatus = CONVERSATION_STATUS_META[conv.status] ?? caseMeta(undefined)
            return (
              <Card key={conv.id} className="overflow-hidden">
                <button
                  onClick={() => setOpenId(isOpen ? null : conv.id)}
                  className="flex w-full items-center gap-4 px-5 py-4 text-left transition-colors hover:bg-slate-800/40"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-slate-700 text-xs font-bold text-slate-200">
                    {initials(conv.customer_name)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-center gap-2">
                      <span className="truncate text-sm font-medium text-slate-200">
                        {conv.customer_name || "Unknown customer"}
                      </span>
                      <span className="rounded-md bg-slate-800 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-slate-400">
                        {conv.channel}
                      </span>
                    </span>
                    <span className="mt-0.5 block truncate text-xs text-slate-500">
                      {conv.last_message
                        ? `${conv.last_message.direction === "inbound" ? "Customer:" : "You:"} ${truncate(conv.last_message.content, 90)}`
                        : "No messages yet"}
                    </span>
                  </span>
                  <span className="hidden shrink-0 items-center gap-3 md:flex">
                    <span className="text-center">
                      <span className="block text-sm font-semibold text-slate-200">
                        {conv.message_count}
                      </span>
                      <span className="block text-[10px] text-slate-500">msgs</span>
                    </span>
                    <StatusBadge meta={convStatus} />
                    <span className="w-20 text-right text-xs text-slate-500">
                      {timeAgo(conv.updated_at ?? conv.created_at)}
                    </span>
                  </span>
                  <svg
                    className={`h-4 w-4 shrink-0 text-slate-500 transition-transform ${isOpen ? "rotate-180" : ""}`}
                    fill="none"
                    viewBox="0 0 24 24"
                    stroke="currentColor"
                  >
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                  </svg>
                </button>

                {isOpen && (
                  <div className="border-t border-slate-800">
                    {conv.case_status === "STOPPED" && (
                      <div className="flex items-center gap-2 border-b border-red-800 bg-red-500/10 px-5 py-2.5">
                        <span className="text-sm">🛑</span>
                        <span className="text-xs text-red-300">
                          STOPPED (User Opt-Out) · Policy Guardrail: Opt-out
                          detected. All automated outreach and retries halted
                          immediately.
                        </span>
                      </div>
                    )}
                    <div className="max-h-96 space-y-2 overflow-y-auto px-5 py-4">
                      {conv.messages.length === 0 ? (
                        <p className="text-sm text-slate-500">No messages recorded.</p>
                      ) : (
                        conv.messages.map((msg) => (
                          <div
                            key={msg.id}
                            className={`flex ${msg.direction === "inbound" ? "justify-start" : "justify-end"}`}
                          >
                            <div
                              className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                                msg.direction === "inbound"
                                  ? "bg-slate-800 text-slate-200"
                                  : "bg-blue-600/20 text-blue-200"
                              }`}
                            >
                              <p className="whitespace-pre-wrap break-words">{msg.content}</p>
                              <p className="mt-1 text-[10px] text-slate-500">
                                {msg.direction === "inbound" ? "Customer" : "Fail2Pay"} ·{" "}
                                {formatDateTime(msg.created_at)}
                              </p>
                            </div>
                          </div>
                        ))
                      )}
                    </div>
                    <div className="flex items-center justify-between border-t border-slate-800/70 bg-slate-900/50 px-5 py-2.5">
                      <span className="text-xs text-slate-500">
                        Started {formatDateTime(conv.created_at)} · {conv.inbound_count} replies
                      </span>
                      {conv.case_id && (
                        <Link
                          to={`/case/${conv.case_id}`}
                          className="text-xs font-medium text-blue-400 hover:text-blue-300"
                        >
                          Open recovery case →
                        </Link>
                      )}
                    </div>
                    {conv.case_id && conv.case_status !== "STOPPED" && (
                      <div className="border-t border-slate-800/70 px-5 py-3">
                        <SimulateMessageControls
                          caseId={conv.case_id}
                          compact
                          onApplied={refresh}
                        />
                      </div>
                    )}
                  </div>
                )}
              </Card>
            )
          })}
        </div>
      )}
    </div>
  )
}