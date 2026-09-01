import { useEffect, useRef, useState, useCallback } from "react"

export interface LiveRealtimeMessage {
  id: string
  conversation_id: string
  direction: string
  content: string
  message_type: string
  extra_data: Record<string, unknown> | null
  created_at: string | null
}

export interface LiveCaseEvent {
  event_type: string
  case_id: string
  occurred_at: string | null
  data: Record<string, unknown>
}

export interface LiveAgentStep {
  step_id: string
  stage: string
  type: string
  label: string
  detail?: string | null
  confidence?: number | null
  latency_ms?: number | null
  occurred_at?: string | null
  extra?: Record<string, unknown>
}

export interface LiveTypingIndicator {
  case_id: string
  is_typing: boolean
  agent_name?: string
  occurred_at?: string | null
}

export interface LiveQuickReply {
  id: string
  label: string
}

export interface LiveQuickRepliesUpdate {
  case_id: string
  conversation_id?: string | null
  occurred_at?: string | null
  data: { quick_replies: LiveQuickReply[] }
}

export interface LiveCaseStateUpdate {
  case_id: string
  occurred_at?: string | null
  data: Record<string, unknown>
}

export interface RealtimeEvent {
  type: string
  conversation_id?: string
  case_id: string
  message?: LiveRealtimeMessage
  event_type?: string
  occurred_at?: string | null
  data?: Record<string, unknown>
  step?: LiveAgentStep
  is_typing?: boolean
  agent_name?: string
}

export type RealtimeStatus = "connecting" | "open" | "closed" | "error"

function buildUrl(caseId: string): string {
  const proto = window.location.protocol === "https:" ? "wss" : "ws"
  const host = window.location.host
  return `${proto}://${host}/ws/cases/${encodeURIComponent(caseId)}`
}

/**
 * Subscribes to the live WhatsApp audit stream for a recovery case.
 *
 * Incoming events are appended (deduped by message id) to `liveMessages`.
 * Reconnects automatically with a small backoff so the dashboard stays
 * subscribed across brief connection drops.
 */
export function useLiveCaseStream(caseId: string | undefined) {
  const [liveMessages, setLiveMessages] = useState<LiveRealtimeMessage[]>([])
  const [liveCaseEvents, setLiveCaseEvents] = useState<LiveCaseEvent[]>([])
  const [liveSteps, setLiveSteps] = useState<LiveAgentStep[]>([])
  const [isTyping, setIsTyping] = useState(false)
  const [liveQuickReplies, setLiveQuickReplies] = useState<LiveQuickReply[]>([])
  const [caseStateUpdate, setCaseStateUpdate] = useState<LiveCaseStateUpdate | null>(null)
  const [status, setStatus] = useState<RealtimeStatus>("closed")
  const [latencyMs, setLatencyMs] = useState<number | null>(null)
  const socketRef = useRef<WebSocket | null>(null)
  const retryRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const attemptsRef = useRef(0)
  const seenRef = useRef<Set<string>>(new Set())
  const eventSeenRef = useRef<Set<string>>(new Set())
  const stepSeenRef = useRef<Set<string>>(new Set())
  const connectStartRef = useRef<number>(0)

  const clearStream = useCallback(() => {
    setLiveMessages([])
    setLiveCaseEvents([])
    setLiveSteps([])
    setIsTyping(false)
    setLiveQuickReplies([])
    setCaseStateUpdate(null)
    seenRef.current = new Set()
    eventSeenRef.current = new Set()
    stepSeenRef.current = new Set()
  }, [])

  useEffect(() => {
    if (!caseId) {
      setStatus("closed")
      clearStream()
      return
    }

    clearStream()
    attemptsRef.current = 0
    setLatencyMs(null)

    const connect = () => {
      connectStartRef.current = Date.now()
      const socket = new WebSocket(buildUrl(caseId))
      socketRef.current = socket

      socket.onopen = () => {
        attemptsRef.current = 0
        setStatus("open")
        // Time to establish the socket — a live "connectivity latency" proxy.
        setLatencyMs(Date.now() - connectStartRef.current)
      }

      socket.onmessage = (evt) => {
        try {
          const data: RealtimeEvent = JSON.parse(evt.data)
          if (data.type === "message" && data.message) {
            const msg = data.message
            if (!seenRef.current.has(msg.id)) {
              seenRef.current.add(msg.id)
              setLiveMessages((prev) => [...prev, msg])
            }
          } else if (data.type === "typing_indicator") {
            setIsTyping(Boolean(data.is_typing))
          } else if (data.type === "reasoning_stream" && data.step) {
            const step = data.step
            if (!stepSeenRef.current.has(step.step_id)) {
              stepSeenRef.current.add(step.step_id)
              setLiveSteps((prev) => [...prev, step])
            }
          } else if (data.type === "agent_step" && data.step) {
            const step = data.step
            if (!stepSeenRef.current.has(step.step_id)) {
              stepSeenRef.current.add(step.step_id)
              setLiveSteps((prev) => [...prev, step])
            }
          } else if (data.type === "quick_replies_updated" && data.data) {
            const replies = (data.data as Record<string, unknown>).quick_replies
            if (Array.isArray(replies)) {
              setLiveQuickReplies(replies as LiveQuickReply[])
            }
          } else if (data.type === "case_state_updated" && data.data) {
            setCaseStateUpdate({
              case_id: data.case_id,
              occurred_at: data.occurred_at ?? null,
              data: data.data,
            })
          } else if (
            data.type === "case_event" &&
            data.event_type
          ) {
            const key = `${data.event_type}:${data.occurred_at ?? ""}:${JSON.stringify(data.data ?? {})}`
            if (!eventSeenRef.current.has(key)) {
              eventSeenRef.current.add(key)
              setLiveCaseEvents((prev) => [
                ...prev,
                {
                  event_type: data.event_type!,
                  case_id: data.case_id,
                  occurred_at: data.occurred_at ?? null,
                  data: data.data ?? {},
                },
              ])
            }
          }
        } catch {
          // Ignore malformed frames.
        }
      }

      socket.onclose = () => {
        setStatus("closed")
        scheduleReconnect()
      }

      socket.onerror = () => {
        setStatus("error")
      }
    }

    const scheduleReconnect = () => {
      if (retryRef.current) return
      const delay = Math.min(2000 * 2 ** attemptsRef.current, 15000)
      attemptsRef.current += 1
      retryRef.current = setTimeout(() => {
        retryRef.current = null
        connect()
      }, delay)
    }

    connect()

    return () => {
      if (retryRef.current) {
        clearTimeout(retryRef.current)
        retryRef.current = null
      }
      if (socketRef.current) {
        socketRef.current.onclose = null
        socketRef.current.close()
        socketRef.current = null
      }
    }
  }, [caseId, clearStream])

  return {
    liveMessages,
    liveCaseEvents,
    liveSteps,
    isTyping,
    liveQuickReplies,
    caseStateUpdate,
    status,
    latencyMs,
  }
}
