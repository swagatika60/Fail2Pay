import { Link } from "react-router-dom"
import {
  Activity,
  ArrowRight,
  Check,
  MessageSquare,
  Search,
  ShieldCheck,
  X,
  Zap,
} from "lucide-react"

const BG = "#0B0F17"

function Brand({ onClick }: { onClick?: () => void }) {
  return (
    <Link
      to="/"
      onClick={onClick}
      className="flex items-center gap-2.5"
      aria-label="Fail2Pay home"
    >
      <span className="flex h-7 w-7 items-center justify-center rounded-md border border-slate-700 bg-slate-900 text-sm font-semibold text-slate-100">
        F
      </span>
      <span className="text-sm font-semibold tracking-tight text-white">
        Fail2Pay
      </span>
    </Link>
  )
}

const PROBLEM_POINTS = [
  "Blind card retries trigger card fatigue & bank blocks",
  "Aggressive static emails that read as spam",
  "Regular churn from one-size-fits-all pestering",
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
    title: "Intelligent Root Cause Diagnosis",
    body: "Distinguishes daily limit caps, card expiries, and mandate failures — so every retry is the right one.",
  },
  {
    icon: MessageSquare,
    title: "Conversational Multi-Channel Interventions",
    body: "Hinglish dialogue with promise-to-pay scheduling that turns an objection into a confirmed future payment.",
  },
  {
    icon: ShieldCheck,
    title: "Deterministic Financial Bounds",
    body: "Max 5 attempts per case, instant opt-out compliance, and zero hallucinated discounts — guardrails are code, not vibes.",
  },
]

const METRICS = [
  { value: "Real-time", label: "Revenue Tracking" },
  { value: "Deterministic", label: "Guardrail Engine" },
  { value: "< 2s", label: "Webhook → Action" },
  { value: "0", label: "Unbounded Actions" },
]

export default function LandingPage() {
  return (
    <div
      className="min-h-screen text-slate-300 antialiased"
      style={{ backgroundColor: BG }}
    >
      {/* Header */}
      <header className="sticky top-0 z-50 h-14 border-b border-slate-800/50 bg-slate-950/80 backdrop-blur-md">
        <div className="mx-auto flex h-14 max-w-6xl items-center justify-between gap-4 px-5">
          <Brand />
          <nav className="hidden items-center gap-6 text-xs font-medium text-slate-400 md:flex">
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
            className="inline-flex items-center gap-1.5 rounded-md bg-white px-3.5 py-1.5 text-xs font-semibold text-slate-900 transition-colors hover:bg-slate-100"
          >
            Launch App
            <ArrowRight className="h-3.5 w-3.5" />
          </Link>
        </div>
      </header>

      {/* Hero */}
      <section className="relative overflow-hidden">
        <div className="pointer-events-none absolute inset-0 bg-[size:4rem_4rem] [background-image:linear-gradient(to_right,rgba(51,65,85,0.12)_1px,transparent_1px),linear-gradient(to_bottom,rgba(51,65,85,0.12)_1px,transparent_1px)]" />
        <div className="relative mx-auto max-w-4xl px-5 pb-16 pt-20 text-center">
          <span className="inline-flex items-center gap-2 rounded-full border border-slate-800 bg-slate-900/60 px-3 py-1 text-xs font-medium text-slate-300 backdrop-blur-sm">
            <Activity className="h-3.5 w-3.5 text-slate-400" />
            Autonomous Revenue Recovery Engine
          </span>
          <h1 className="mx-auto mt-6 max-w-3xl text-4xl font-semibold leading-tight tracking-tight text-white md:text-5xl">
            Autonomous revenue recovery for Indian payment failures
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-base font-normal leading-relaxed text-slate-400 sm:text-lg">
            Fail2Pay connects to Razorpay and payment gateways to diagnose failed
            transactions, orchestrate conversational WhatsApp outreach, and
            recover abandoned revenue within deterministic policy guardrails.
          </p>
          <div className="mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <Link
              to="/dashboard"
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg bg-white px-5 py-2.5 text-sm font-medium text-slate-950 shadow-sm transition-all hover:bg-slate-100 sm:w-auto"
            >
              Launch Recovery Dashboard
              <ArrowRight className="h-4 w-4" />
            </Link>
            <Link
              to="/simulation"
              className="inline-flex w-full items-center justify-center gap-2 rounded-lg border border-slate-700/60 bg-slate-900/80 px-5 py-2.5 text-sm font-medium text-slate-300 transition-all hover:text-white sm:w-auto"
            >
              <Zap className="h-4 w-4" />
              Simulate Live Webhook
            </Link>
          </div>
        </div>
      </section>

      {/* Live Recovery Preview */}
      <section className="mx-auto max-w-3xl px-5 pb-16">
        <div className="rounded-xl border border-slate-800/80 bg-[#0E131F] p-6">
          <div className="mb-5 flex items-center justify-between">
            <div className="flex items-center gap-2">
              <span className="relative flex h-2 w-2">
                <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-500 opacity-60" />
                <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
              </span>
              <span className="text-[11px] font-medium uppercase tracking-wider text-slate-500">
                Live Recovery Event
              </span>
            </div>
            <span className="text-[11px] tabular-nums text-slate-600">
              just now
            </span>
          </div>

          {/* Event row */}
          <div className="grid grid-cols-1 gap-3 border-b border-slate-800/80 pb-5 sm:grid-cols-3">
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Event
              </p>
              <p className="mt-1 text-sm text-slate-200">
                payment.failed · ₹11,999
              </p>
            </div>
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Diagnosis
              </p>
              <p className="mt-1 inline-flex rounded border border-amber-500/20 bg-amber-500/10 px-1.5 text-xs font-medium text-amber-400">
                TRANSACTION_LIMIT_EXCEEDED
              </p>
            </div>
            <div>
              <p className="text-[11px] font-medium uppercase tracking-wide text-slate-500">
                Action
              </p>
              <p className="mt-1 text-sm text-slate-200">
                WhatsApp · 2-part split
              </p>
            </div>
          </div>

          {/* Chat bubble preview */}
          <div className="mt-5 rounded-lg border border-slate-800/80 bg-slate-900/50 p-4">
            <div className="mb-1.5 flex items-center gap-1.5 text-[11px] text-slate-400">
              <MessageSquare className="h-3 w-3 text-emerald-500" />
              WhatsApp · Devanand Verma
            </div>
            <div className="rounded-lg rounded-tl-none bg-slate-800 px-3.5 py-2.5 text-sm leading-relaxed text-slate-100">
              Namaste Devanandji, no stress. We can split the ₹11,999 into 2
              installments of <span className="font-semibold">₹5,999.50</span>{" "}
              each. Here is Part 1:
            </div>
            <div className="mt-2.5 w-fit max-w-sm rounded-md border border-slate-800 bg-slate-900/90 p-3">
              <div className="flex items-center justify-between gap-4">
                <div>
                  <p className="text-[11px] text-slate-500">Fail2Pay · Inv INV-03E3E982</p>
                  <p className="text-sm font-medium text-slate-100">Pay ₹5,999.50 (Part 1 of 2)</p>
                  <p className="text-[11px] text-slate-500">via Razorpay</p>
                </div>
                <button
                  type="button"
                  className="rounded-md bg-white px-3 py-1.5 text-xs font-semibold text-slate-900 transition-colors hover:bg-slate-100"
                >
                  Pay Now ₹5,999.50
                </button>
              </div>
            </div>
          </div>
        </div>
      </section>

      {/* Problem vs Solution */}
      <section id="features" className="mx-auto max-w-6xl px-5 py-16">
        <div className="mx-auto mb-10 max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
            The Problem
          </p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
            Blind retries are losing you money
          </h2>
          <p className="mt-4 text-slate-400">
            Retry-and-pray burns relationships. Fail2Pay replaces every blind
            action with a reasoned, bounded one.
          </p>
        </div>

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Traditional */}
          <div className="rounded-xl border border-slate-800/80 bg-[#0E131F] p-6">
            <div className="mb-5 flex items-center justify-between">
              <h3 className="text-base font-semibold text-slate-100">
                Traditional Retries
              </h3>
              <span className="rounded-full border border-slate-800 bg-slate-900/60 px-2.5 py-1 text-[11px] font-medium text-slate-500">
                Legacy
              </span>
            </div>
            <ul className="space-y-3.5">
              {PROBLEM_POINTS.map((point) => (
                <li key={point} className="flex items-start gap-3 text-sm text-slate-300">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border border-slate-800 bg-slate-900/60">
                    <X className="h-3 w-3 text-slate-500" />
                  </span>
                  <span className="text-slate-400">{point}</span>
                </li>
              ))}
            </ul>
          </div>

          {/* Fail2Pay */}
          <div className="rounded-xl border border-slate-700/60 bg-[#0E131F] p-6">
            <div className="mb-5 flex items-center justify-between">
              <h3 className="text-base font-semibold text-white">Fail2Pay Agent</h3>
              <span className="inline-flex items-center gap-1 rounded-full border border-slate-800 bg-slate-900/60 px-2.5 py-1 text-[11px] font-medium text-slate-300">
                Autonomous
              </span>
            </div>
            <ul className="space-y-3.5">
              {SOLUTION_POINTS.map((point) => (
                <li key={point} className="flex items-start gap-3 text-sm text-slate-200">
                  <span className="mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded border border-emerald-500/30 bg-emerald-500/10">
                    <Check className="h-3 w-3 text-emerald-400" />
                  </span>
                  <span className="text-slate-200">{point}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      </section>

      {/* Architecture / Feature cards */}
      <section id="architecture" className="mx-auto max-w-6xl px-5 py-16">
        <div className="mx-auto mb-10 max-w-2xl text-center">
          <p className="text-xs font-semibold uppercase tracking-widest text-slate-500">
            Core Architecture
          </p>
          <h2 className="mt-3 text-3xl font-semibold tracking-tight text-white sm:text-4xl">
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
              className="rounded-xl border border-slate-800/80 bg-[#0E131F] p-6 transition-colors hover:border-slate-700"
            >
              <div className="mb-5 inline-flex h-10 w-10 items-center justify-center rounded-lg border border-slate-800 bg-slate-900/60">
                <feature.icon className="h-5 w-5 text-slate-300" />
              </div>
              <h3 className="text-base font-semibold text-slate-100">
                {feature.title}
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-slate-400">
                {feature.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Stats bar */}
      <section id="proof" className="mx-auto max-w-6xl px-5 py-16">
        <div className="grid grid-cols-2 divide-slate-800 overflow-hidden rounded-xl border border-slate-800/80 bg-[#0E131F] md:grid-cols-4 md:divide-x">
          {METRICS.map((metric) => (
            <div key={metric.label} className="flex flex-col items-center justify-center px-4 py-8 text-center">
              <p className="text-2xl font-semibold tracking-tight text-white">
                {metric.value}
              </p>
              <p className="mt-1 text-xs font-medium text-slate-500">
                {metric.label}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* CTA band */}
      <section className="mx-auto max-w-3xl px-5 py-16 text-center">
        <h2 className="text-3xl font-semibold tracking-tight text-white sm:text-4xl">
          Ready to start recovering lost revenue?
        </h2>
        <p className="mx-auto mt-4 max-w-xl text-slate-400">
          Spin up the agent, point it at your gateway, and watch abandoned
          revenue come back — autonomously and in-bounds.
        </p>
        <Link
          to="/dashboard"
          className="mt-8 inline-flex items-center gap-2 rounded-lg bg-white px-6 py-2.5 text-sm font-medium text-slate-950 shadow-sm transition-colors hover:bg-slate-100"
        >
          Launch Recovery Dashboard
          <ArrowRight className="h-4 w-4" />
        </Link>
      </section>

      {/* Footer */}
      <footer className="border-t border-slate-800/50 py-10">
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
