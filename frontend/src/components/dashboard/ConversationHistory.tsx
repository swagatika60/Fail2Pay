import type { Conversation } from "../../types/analytics"

interface ConversationHistoryProps {
  conversations: Conversation[]
}

function formatDateTime(dateStr: string | null): string {
  if (!dateStr) return ""
  return new Date(dateStr).toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export default function ConversationHistory({
  conversations,
}: ConversationHistoryProps) {
  if (conversations.length === 0) {
    return (
      <div className="rounded-lg bg-slate-800/50 p-4 text-center text-sm text-slate-500">
        No conversations yet
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {conversations.map((conv) => (
        <div
          key={conv.id}
          className="rounded-lg border border-slate-700/50 bg-slate-800/30 p-4"
        >
          <div className="mb-3 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="inline-block rounded-full bg-green-500/20 px-2.5 py-0.5 text-xs font-medium text-green-400">
                💬 {conv.channel}
              </span>
              <span className="text-xs text-slate-500">
                {conv.messages.length} messages
              </span>
            </div>
            <span className="text-xs text-slate-500">
              {formatDateTime(conv.created_at)}
            </span>
          </div>

          <div className="space-y-2">
            {conv.messages.map((msg) => {
              const isInbound = msg.direction === "inbound"
              return (
                <div
                  key={msg.id}
                  className={`flex ${isInbound ? "justify-start" : "justify-end"}`}
                >
                  <div
                    className={`max-w-[80%] rounded-lg px-3 py-2 text-sm ${
                      isInbound
                        ? "rounded-bl-none bg-slate-700 text-slate-200"
                        : "rounded-br-none bg-blue-600 text-white"
                    }`}
                  >
                    <div className="mb-0.5 flex items-center gap-1.5">
                      <span className="text-[10px] opacity-60">
                        {isInbound ? "📥 Customer" : "📤 Agent"}
                      </span>
                      <span className="text-[10px] opacity-40">
                        {formatDateTime(msg.created_at)}
                      </span>
                    </div>
                    <div className="whitespace-pre-wrap">{msg.content}</div>
                    {msg.extra_data && (
                      <div className="mt-1 text-[10px] opacity-40">
                        {typeof msg.extra_data.delivery_status === "string" &&
                          `• ${msg.extra_data.delivery_status}`}
                        {typeof msg.extra_data.language === "string" &&
                          ` • ${msg.extra_data.language}`}
                      </div>
                    )}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      ))}
    </div>
  )
}
