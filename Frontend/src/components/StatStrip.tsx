export interface StatItem {
  label: string
  value: string
  tone?: 'success' | 'warning' | 'danger' | 'accent'
}

interface StatStripProps {
  items: StatItem[]
}

export function StatStrip({ items }: StatStripProps) {
  return (
    <section className="stat-strip" aria-label="Summary">
      {items.map((item) => (
        <div key={item.label} className="stat">
          <span className="stat-label">{item.label}</span>
          <span className={`stat-value ${item.tone ? `tone-${item.tone}` : ''}`}>{item.value}</span>
        </div>
      ))}
    </section>
  )
}
