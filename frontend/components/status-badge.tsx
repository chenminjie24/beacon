'use client'

export default function StatusBadge({ value }: { value: string }) {
  const upper = value.toUpperCase()
  const bad = ['FAILED', 'REJECTED', 'OFFLINE', 'ERROR'].some((x) => upper.includes(x))
  const warn = ['PARTIAL', 'PENDING', 'WARN', 'CANCEL'].some((x) => upper.includes(x))
  const klass = bad ? 'bad' : warn ? 'warn' : 'ok'
  return <span className={`badge ${klass}`}>{value}</span>
}
