import { Link } from "react-router-dom"
import {
  Activity,
  ArrowRight,
  BarChart3,
  MessageSquare,
  Search,
  ShieldCheck,
  Sparkles,
  TrendingUp,
  Zap,
} from "lucide-react"

const NAVY_BG = "#0b132b"
const NAVY_CARD = "#1c2541"

function Brand({ onClick }: { onClick?: () => void }) {
  return (
    <Link
      to="/"
      onClick={onClick}
      className="flex items-center gap-2.5"
      aria-label="Fail2Pay home"
    >
      <span className="flex h-9 w-9 items-center justify-center rounded-lg bg-indigo-600 text-base font-black text-white shadow-lg shadow-indigo-600/30">
        F
      </span>
      <span className="text-lg font-bold tracking-tight text-slate-50">
        Fail2Pay
      </span>
    </Link>
  )
}

const PROBLEM_POINTS = [
  "Blind card retries trigger card fatigue & bank blocks",
  "Aggressive static emails that read as spam",
  "Regular customer churn from one-size-fits-all pestering",
  "Zero visibility into broken mandates until money is lost",
]

const SOLUTION_POINTS = [
  "Root-cause failure diagnosis before any touch",
  "Intelligent EMI split generation (2x / 4x) customers accept",
  "Conversational WhatsApp outreach in Hinglish",
  "Verified captured settlements — only real money counts",
]

const FEATURES = [
  {
    icon: Search,
    accent: "text-cyan-400",
    ring: "ring-cyan-500/20",
    bg: "bg-cyan-500/10",
    title: "Intelligent Root Cause Diagnosis",
    body: "Distinguishes daily limit caps, card expiries, and mandate failures — so every retry is the right one.",
  },
  {
    icon: MessageSquare,
    accent: "text-indigo-400",
    ring: "ring-indigo-500/20",
    bg: "bg-indigo-500/10",
    title: "Conversational Multi-Channel Interventions",
    body: "Hinglish dialogue with promise-to-pay scheduling that turns an objection into a confirmed future payment.",
  },
  {
    icon: ShieldCheck,
    accent: "text-emerald-400",
    ring: "ring-emerald-500/20",
    bg: "bg-emerald-500/10",
    title: "Deterministic Financial Bounds",
    body: "Max 5 attempts per case, instant opt-out compliance, and zero hallucinated discounts — guardrails are code, not vibes.",
  },
]

const METRICS = [
  {
    icon: TrendingUp,
    accent: "text-emerald-400",
    value: "₹3.42 L",
    label: "Recovered",
  },
  {
    icon: BarChart3,
    accent: "text-cyan-400",
    value: "53.2%",
    label: "Recovery Yield",
  },
  {
    icon: Zap,
    accent: "text-indigo-400",
    value: "10.5d",
    label: "Avg Cycle",
  },
  {
    icon: ShieldCheck,
    accent: "text-emerald-400",
    value: "Zero",
    label: "Unbounded Actions",
  },
]

export default function LandingPage() {
  return (
    <div className="min-h-screen text-slate-100 antialiased" style={{ backgroundColor: NAVY_BG }}>
      {/* Header */}
      <header className="sticky top-0 z-40 border-b border-white/10 bg-[#0b132b]/90 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-5 py-4">
          <Brand />
          <nav className="hidden items-center gap-7 text-sm text-slate-400 md:flex">
            <a href="#features" className="transition-colors hover:text-slate-100">
              Features
            </a>
            <a href="#architecture" className="transition-colors hover:text-slate-100">
              Architecture
            </a>
            <a href="#proof" className="transition-colors hover:text-slate-100">
              Proof
            </a>
            <a
              href="https://github.com"
              target="_blank"
              rel="noreferrer"
              className="transition-colors hover:text-slate-100"
            >
              GitHub
            </a>
          </nav>
          <Link
            to="/dashboard"
            className="inline-flex items-center gap-1.5 rounded-lg bg-indigo-600 px-4 py-2 text-sm font-semibold text-white shadow-lg shadow-indigo-600/30 transition-colors hover:bg-indigo-500"
          >
            Go to App
            <ArrowRight className="h-4 w-4" />
          </Link>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute -top-40 left-1/2 h-[480px] w-[720px] -translate-x-1/2 rounded-full bg-indigo-600/20 blur-3xl" />
        <div className="pointer-events-none absolute top-10 right-0 h-64 w-64 rounded-full bg-cyan-500/10 blur-3xl" />
        <div className="pointer-events-none absolute bottom-0 left-0 h-64 w-64 rounded-full bg-emerald-500/10 blur-3xl" />

        <div className="relative mx-auto max-w-4xl px-5 pb-20 pt-20 text-center">
          <span className="inline-flex items-center rounded-full border border-emerald-500/30 bg-emerald-500/10 px-3 py-1 text-xs font-medium text-emerald-300">
            <Activity className="mr-1.5 inline h-3.5 w-3.5 text-emerald-400" />
            Autonomous Revenue Recovery Engine
          </span>
          <h1 className="mx-auto mt-6 max-w-3xl text-4xl font-black leading-tight tracking-tight text-slate-50 sm:text-5xl md:text-6xl">
            Find revenue that's slipping away —{" "}
            <span className="bg-gradient-to-r from-cyan-400 via-indigo-400 to-emerald-400 bg-clip-text text-transparent">
              and win it back autonomously.
            </span>
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-slate-400 sm:text-lg">
            Fail2Pay connects to your payment gateways to diagnose failed
            transactions, orchestrate Hinglish multi-channel outreach, and
            recover abandoned revenue with bounded policy guardrails.
          </p>
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              to="/dashboard"
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-indigo-600 px-6 py-3 text-sm font-semibold text-white shadow-xl shadow-indigo-600/30 transition-colors hover:bg-indigo-500 sm:w-auto"
            >
              Launch Recovery Dashboard
              <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              to="/simulation"
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-white/15 bg-white/5 px-6 py-3 text-sm font-semibold text-slate-200 backdrop-blur transition-colors hover:border-white/25 hover:bg-white/10 sm:w-auto"
            >
              <Zap className="h-4 w-4 text-emerald-400" />
              Simulate Live Webhook
            </Link>
          </div>
        </div>
      </section>

      {/* Problem vs Solution */}
      <section id="features" className="mx-auto max-w-6xl px-5 py-16">
        <div className="mx-auto mb-10 max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-cyan-400">
            The Problem
          </p>
          <h2 className="mt-3 text-3xl font-black tracking-tight text-slate-50 sm:text-4xl">
            Blind retries are losing you money
          </h2>
          <p className="mt-4 text-slate-400">
            Retry-and-pray burns relationships. Fail2Pay replaces every blind
            action with a reasoned, bounded one.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Traditional */}
          <div
            className="group relative overflow-hidden rounded-2xl border border-white/10 p-7 transition-colors hover:border-rose-500/40"
            style={{ backgroundColor: NAVY_CARD }}
          >
            <div className="mb-5 flex items-center justify-between">
              <h3 className="text-lg font-bold text-slate-100">
                Traditional Retries
              </h3>
              <span className="rounded-full bg-rose-500/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-rose-400">
                Legacy
              </span>
            </div>
            <ul className="space-y-3.5">
              {PROBLEM_POINTS.map((point) => (
                <li key={point} className="flex items-start gap-3 text-sm text-slate-300">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-rose-500/15">
                    <span className="text-xs font-bold text-rose-400">✕</span>
                  </span>
                  <span className="opacity-70 transition-opacity group-hover:opacity-100">
                    {point}
                  </span>
                </li>
              ))}
            </ul>
          </div>

          {/* Fail2Pay */}
          <div
            className="group relative overflow-hidden rounded-2xl border border-indigo-500/40 p-7 shadow-xl shadow-indigo-600/10 transition-colors hover:border-indigo-400"
            style={{ backgroundColor: NAVY_CARD }}
          >
            <div className="mb-5 flex items-center justify-between">
              <h3 className="text-lg font-bold text-slate-50">Fail2Pay Agent</h3>
              <span className="inline-flex items-center gap-1 rounded-full bg-indigo-500/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-wider text-indigo-400">
                <Sparkles className="h-3 w-3" />
                Autonomous
              </span>
            </div>
            <ul className="space-y-3.5">
              {SOLUTION_POINTS.map((point) => (
                <li key={point} className="flex items-start gap-3 text-sm text-slate-200">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-500/15">
                    <span className="text-xs font-bold text-emerald-400">✓</span>
                  </span>
                  <span className="transition-opacity group-hover:opacity-100">
                    {point}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Architecture / Feature cards */}
      <section id="architecture" className="mx-auto max-w-6xl px-5 py-16">
        <div className="mx-auto mb-10 max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-indigo-400">
            Core Architecture
          </p>
          <h2 className="mt-3 text-3xl font-black tracking-tight text-slate-50 sm:text-4xl">
            Bounded guardrails, not guesswork
          </h2>
          <p className="mt-4 text-slate-400">
            An agent that reasons — but stays strictly inside deterministic
            financial and compliance limits.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 md:grid-cols-3">
          {FEATURES.map((feature) => (
            <div
              key={feature.title}
              className={`group rounded-2xl border border-white/10 p-7 ring-1 ring-transparent transition-all hover:-translate-y-1 hover:ring-2 ${feature.ring}`}
              style={{ backgroundColor: NAVY_CARD }}
            >
              <div
                className={`mb-5 inline-flex h-12 w-12 items-center justify-center rounded-xl ${feature.bg} ${feature.accent}`}
              >
                <feature.icon className="h-6 w-6" />
              </div>
              <h3 className="text-lg font-bold text-slate-100">{feature.title}</h3>
              <p className="mt-2.5 text-sm leading-relaxed text-slate-400">
                {feature.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Live proof metric strip */}
      <section id="proof" className="mx-auto max-w-6xl px-5 py-16">
        <div
          className="relative overflow-hidden rounded-3xl border border-white/10 p-10"
          style={{ backgroundColor: NAVY_CARD }}
        >
          <div className="pointer-events-none absolute -right-24 -top-24 h-64 w-64 rounded-full bg-emerald-500/10 blur-3xl" />
          <div className="pointer-events-none absolute -left-24 -bottom-24 h-64 w-64 rounded-full bg-cyan-500/10 blur-3xl" />
          <div className="relative grid grid-cols-2 gap-8 md:grid-cols-4">
            {METRICS.map((metric) => (
              <div key={metric.label} className="text-center">
                <div
                  className={`mx-auto mb-3 inline-flex h-10 w-10 items-center justify-center rounded-xl bg-white/5 ${metric.accent}`}
                >
                  <metric.icon className="h-5 w-5" />
                </div>
                <p className="text-3xl font-black tracking-tight text-slate-50">
                  {metric.value}
                </p>
                <p className="mt-1 text-xs font-medium uppercase tracking-wide text-slate-500">
                  {metric.label}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA band */}
      <section className="mx-auto max-w-6xl px-5 py-16 text-center">
        <h2 className="text-3xl font-black tracking-tight text-slate-50 sm:text-4xl">
          Ready to stop losing recovered revenue?
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-slate-400">
          Spin up the agent, point it at your gateway, and watch abandoned
          revenue come back — autonomously and in-bounds.
        </p>
        <Link
          to="/dashboard"
          className="mt-8 inline-flex items-center gap-2 rounded-lg bg-gradient-to-r from-cyan-500 to-indigo-600 px-7 py-3.5 text-sm font-bold text-white shadow-xl shadow-indigo-600/30 transition-opacity hover:opacity-90"
        >
          Launch Recovery Dashboard
          <ArrowRight className="h-4 w-4" />
        </Link>
      </section>

      {/* Footer */}
      <footer className="border-t border-white/10 py-10">
        <div className="mx-auto flex max-w-6xl flex-col items-center justify-between gap-6 px-5 sm:flex-row">
          <Brand />
          <p className="text-center text-xs text-slate-500">
            Fail2Pay — Autonomous revenue recovery with bounded guardrails.
            © {new Date().getFullYear()} Fail2Pay.
          </p>
          <div className="flex items-center gap-5 text-xs text-slate-500">
            <a href="#features" className="transition-colors hover:text-slate-200">
              Features
            </a>
            <a href="#architecture" className="transition-colors hover:text-slate-200">
              Architecture
            </a>
            <a
              href="https://github.com"
              target="_blank"
              rel="noreferrer"
              className="transition-colors hover:text-slate-200"
            >
              GitHub
            </a>
          </div>
        </div>
      </footer>
    </div>
  )
}
