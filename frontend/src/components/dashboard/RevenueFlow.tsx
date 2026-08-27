import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts"
import type { RevenueSummary } from "../../types/analytics"
import { formatCurrency } from "./MetricCard"

interface RevenueFlowProps {
  data: RevenueSummary
}

const FLOW_COLORS = [
  "#3b82f6", // Expected - blue
  "#ef4444", // At Risk - red
  "#f59e0b", // Recovery In Progress - amber
  "#22c55e", // Recovered - green
  "#6b7280", // Lost - gray
]

export default function RevenueFlow({ data }: RevenueFlowProps) {
  const flowData = [
    { name: "Expected", value: data.expected_revenue, fill: FLOW_COLORS[0] },
    { name: "At Risk", value: data.revenue_at_risk, fill: FLOW_COLORS[1] },
    {
      name: "In Progress",
      value: data.recovery_in_progress,
      fill: FLOW_COLORS[2],
    },
    { name: "Recovered", value: data.recovered_revenue, fill: FLOW_COLORS[3] },
    { name: "Lost", value: data.lost_revenue, fill: FLOW_COLORS[4] },
  ]

  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900 p-6">
      <h2 className="mb-4 text-lg font-semibold text-slate-100">
        Revenue Flow
      </h2>

      {/* Flow arrows */}
      <div className="mb-6 flex items-center justify-center gap-2 text-sm">
        {["Expected", "At Risk", "Recovery", "Recovered / Lost"].map(
          (step, i) => (
            <div key={step} className="flex items-center gap-2">
              <span className="rounded-lg bg-slate-800 px-3 py-1.5 text-slate-300">
                {step}
              </span>
              {i < 3 && (
                <svg
                  className="h-4 w-4 text-slate-500"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M9 5l7 7-7 7"
                  />
                </svg>
              )}
            </div>
          ),
        )}
      </div>

      {/* Bar chart */}
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={flowData} margin={{ top: 10, right: 10, left: 10, bottom: 5 }}>
            <XAxis
              dataKey="name"
              tick={{ fill: "#94a3b8", fontSize: 12 }}
              axisLine={{ stroke: "#334155" }}
              tickLine={false}
            />
            <YAxis
              tick={{ fill: "#94a3b8", fontSize: 12 }}
              axisLine={{ stroke: "#334155" }}
              tickLine={false}
              tickFormatter={(v: number) => formatCurrency(v)}
            />
            <Tooltip
              formatter={(value) => formatCurrency(Number(value))}
              contentStyle={{
                backgroundColor: "#1e293b",
                border: "1px solid #334155",
                borderRadius: "8px",
                color: "#e2e8f0",
              }}
            />
            <Bar dataKey="value" radius={[6, 6, 0, 0]}>
              {flowData.map((entry, index) => (
                <Cell key={`cell-${index}`} fill={entry.fill} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}
