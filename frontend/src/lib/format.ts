export function formatINR(paise: number): string {
  const rupees = Number(paise) / 100
  if (rupees >= 10000000) return `₹${(rupees / 10000000).toFixed(2)} Cr`
  if (rupees >= 100000) return `₹${(rupees / 100000).toFixed(2)} L`
  if (rupees >= 1000) return `₹${(rupees / 1000).toFixed(1)} K`
  return `₹${Math.round(rupees).toLocaleString("en-IN")}`
}

export function formatINRFull(paise: number): string {
  const rupees = Number(paise) / 100
  return `₹${rupees.toLocaleString("en-IN", {
    maximumFractionDigits: 2,
  })}`
}

export function formatPercent(ratio: number, digits = 1): string {
  const value = Number(ratio)
  if (Number.isNaN(value)) return "—"
  return `${(value * 100).toFixed(digits)}%`
}

export function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "—"
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return "—"
  return d.toLocaleDateString("en-IN", {
    day: "numeric",
    month: "short",
    year: "numeric",
  })
}

export function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return "—"
  const d = new Date(dateStr)
  if (Number.isNaN(d.getTime())) return "—"
  return d.toLocaleString("en-IN", {
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  })
}

export function timeAgo(dateStr: string | null | undefined): string {
  if (!dateStr) return "—"
  const date = new Date(dateStr)
  const seconds = Math.floor((Date.now() - date.getTime()) / 1000)
  if (Number.isNaN(seconds)) return "—"
  if (seconds < 60) return "just now"
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.floor(hours / 24)
  if (days < 7) return `${days}d ago`
  const weeks = Math.floor(days / 7)
  if (weeks < 5) return `${weeks}w ago`
  return formatDate(dateStr)
}

export function initials(name: string | null | undefined): string {
  if (!name) return "?"
  const parts = name.trim().split(/\s+/)
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

export function truncate(text: string | null | undefined, max = 80): string {
  if (!text) return ""
  return text.length > max ? `${text.slice(0, max)}…` : text
}