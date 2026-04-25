import { useEffect, useMemo, useState } from 'react'

export function PageHeader({ eyebrow, title, description, actions }) {
    return (
        <header className="page-header">
            <div>
                {eyebrow ? <div className="eyebrow">{eyebrow}</div> : null}
                <h1>{title}</h1>
                {description ? <p>{description}</p> : null}
            </div>
            {actions ? <div className="page-actions">{actions}</div> : null}
        </header>
    )
}

export function Panel({ title, meta, actions, children, className = '' }) {
    return (
        <section className={`panel ${className}`.trim()}>
            {(title || meta || actions) ? (
                <div className="panel-header">
                    <div>
                        {title ? <h2>{title}</h2> : null}
                        {meta ? <p>{meta}</p> : null}
                    </div>
                    {actions ? <div className="panel-actions">{actions}</div> : null}
                </div>
            ) : null}
            {children}
        </section>
    )
}

export function MetricCard({ label, value, unit, sub, trend, tone = 'neutral' }) {
    const trendTone = trend?.value > 0 ? 'positive' : trend?.value < 0 ? 'negative' : 'neutral'
    return (
        <section className={`metric-card tone-${tone}`}>
            <div className="metric-label">{label}</div>
            <div className="metric-value">
                {value}
                {unit ? <span>{unit}</span> : null}
            </div>
            <div className="metric-footer">
                {sub ? <span>{sub}</span> : <span />}
                {trend ? (
                    <span className={`trend trend-${trendTone}`}>
                        {trend.value > 0 ? 'up' : trend.value < 0 ? 'down' : 'flat'} {Math.abs(trend.value)}{trend.unit || ''}
                    </span>
                ) : null}
            </div>
        </section>
    )
}

export function StatusBadge({ tone = 'neutral', children }) {
    return <span className={`status-badge status-${tone}`}>{children}</span>
}

export function Button({ children, variant = 'default', size = 'md', icon: Icon, className = '', ...props }) {
    return (
        <button className={`button button-${variant} button-${size} ${className}`.trim()} {...props}>
            {Icon ? <Icon size={16} /> : null}
            <span>{children}</span>
        </button>
    )
}

export function SegmentedControl({ items, value, onChange }) {
    return (
        <div className="segmented-control">
            {items.map(item => (
                <button
                    key={item.value}
                    type="button"
                    className={value === item.value ? 'active' : ''}
                    onClick={() => onChange(item.value)}
                >
                    {item.label}
                </button>
            ))}
        </div>
    )
}

export function TextInput({ icon: Icon, className = '', ...props }) {
    return (
        <label className={`input-shell ${className}`.trim()}>
            {Icon ? <Icon size={16} /> : null}
            <input {...props} />
        </label>
    )
}

export function EmptyState({ title = '暂无数据', detail }) {
    return (
        <div className="empty-state">
            <div className="empty-title">{title}</div>
            {detail ? <div className="empty-detail">{detail}</div> : null}
        </div>
    )
}

export function DataTable({ rows = [], columns = [], pageSize = 0, empty = '暂无数据', rowKey, onRowClick, activeKey }) {
    const [page, setPage] = useState(1)

    useEffect(() => {
        setPage(1)
    }, [rows, columns, pageSize])

    const totalPages = pageSize > 0 ? Math.max(1, Math.ceil(rows.length / pageSize)) : 1
    const safePage = Math.min(page, totalPages)
    const start = pageSize > 0 ? (safePage - 1) * pageSize : 0
    const visibleRows = pageSize > 0 ? rows.slice(start, start + pageSize) : rows

    if (!rows.length) return <EmptyState title={empty} />

    return (
        <>
            <div className="table-wrap">
                <table className="data-table">
                    <thead>
                        <tr>
                            {columns.map(col => <th key={col.key}>{col.label || col.key}</th>)}
                        </tr>
                    </thead>
                    <tbody>
                        {visibleRows.map((row, index) => {
                            const key = rowKey ? rowKey(row, index) : row.id ?? row.chapter ?? `${start}-${index}`
                            const active = activeKey !== undefined && activeKey === key
                            return (
                                <tr
                                    key={key}
                                    className={`${onRowClick ? 'clickable-row' : ''} ${active ? 'active-row' : ''}`.trim()}
                                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                                >
                                    {columns.map(col => (
                                        <td key={col.key} className={col.className || ''}>
                                            {col.render ? col.render(row[col.key], row) : formatCell(row[col.key])}
                                        </td>
                                    ))}
                                </tr>
                            )
                        })}
                    </tbody>
                </table>
            </div>
            {pageSize > 0 && rows.length > pageSize ? (
                <div className="pagination">
                    <button type="button" onClick={() => setPage(p => Math.max(1, p - 1))} disabled={safePage <= 1}>上一页</button>
                    <span>{safePage} / {totalPages} · {rows.length} 条</span>
                    <button type="button" onClick={() => setPage(p => Math.min(totalPages, p + 1))} disabled={safePage >= totalPages}>下一页</button>
                </div>
            ) : null}
        </>
    )
}

export function Sparkline({ values = [], height = 160 }) {
    const points = useMemo(() => {
        const nums = values.map(v => Number(v) || 0)
        if (nums.length === 0) return ''
        const min = Math.min(...nums)
        const max = Math.max(...nums)
        const span = max - min || 1
        return nums.map((v, i) => {
            const x = nums.length === 1 ? 50 : (i / (nums.length - 1)) * 100
            const y = height - ((v - min) / span) * (height - 28) - 14
            return `${x},${y}`
        }).join(' ')
    }, [height, values])

    if (!values.length) return <EmptyState title="暂无序列数据" />

    return (
        <svg className="sparkline" viewBox={`0 0 100 ${height}`} preserveAspectRatio="none" role="img">
            <defs>
                <linearGradient id="sparkline-fill" x1="0" x2="0" y1="0" y2="1">
                    <stop offset="0%" stopColor="currentColor" stopOpacity="0.26" />
                    <stop offset="100%" stopColor="currentColor" stopOpacity="0" />
                </linearGradient>
            </defs>
            <polyline points={`0,${height - 8} ${points} 100,${height - 8}`} className="sparkline-area" />
            <polyline points={points} className="sparkline-line" />
        </svg>
    )
}

export function QualityHeatmap({ results = [] }) {
    if (!results.length) return <EmptyState title="暂无 audit 数据" detail="后端 /api/audit 还没有返回结果" />

    return (
        <div className="quality-grid" role="list" aria-label="质量热力图">
            {results.map(item => {
                const tone = auditTone(item.verdict)
                return (
                    <div
                        key={item.chapter}
                        className={`quality-cell quality-${tone}`}
                        title={`第 ${item.chapter} 章 · ${item.verdict}`}
                        role="listitem"
                    >
                        {item.chapter}
                    </div>
                )
            })}
        </div>
    )
}

export function ProgressBar({ value = 0, tone = 'primary' }) {
    const pct = Math.max(0, Math.min(100, Number(value) || 0))
    return (
        <div className="progress-bar">
            <span className={`progress-fill progress-${tone}`} style={{ width: `${pct}%` }} />
        </div>
    )
}

export function KeyValueList({ items }) {
    return (
        <dl className="kv-list">
            {items.map(item => (
                <div key={item.label}>
                    <dt>{item.label}</dt>
                    <dd>{item.value ?? '-'}</dd>
                </div>
            ))}
        </dl>
    )
}

export function formatNumber(value, options = {}) {
    const n = Number(value)
    if (!Number.isFinite(n)) return '-'
    if (options.compact && Math.abs(n) >= 10000) {
        return `${new Intl.NumberFormat('zh-CN', { maximumFractionDigits: 1 }).format(n / 10000)}万`
    }
    return new Intl.NumberFormat('zh-CN', options).format(n)
}

export function formatPercent(value, digits = 1) {
    const n = Number(value)
    if (!Number.isFinite(n)) return '-'
    return `${n.toFixed(digits)}%`
}

export function formatCell(value) {
    if (value === null || value === undefined || value === '') return '-'
    if (typeof value === 'boolean') return value ? 'true' : 'false'
    if (Array.isArray(value)) return value.join(', ')
    if (typeof value === 'object') {
        try {
            return JSON.stringify(value)
        } catch {
            return String(value)
        }
    }
    const text = String(value)
    return text.length > 160 ? `${text.slice(0, 160)}...` : text
}

export function toArray(value) {
    return Array.isArray(value) ? value : []
}

export function pickNumber(row, keys) {
    for (const key of keys) {
        const n = Number(row?.[key])
        if (Number.isFinite(n)) return n
    }
    return 0
}

export function auditTone(verdict = '') {
    const v = String(verdict).toUpperCase()
    if (v === 'PASS') return 'pass'
    if (v.includes('WARN')) return 'warn'
    if (v.includes('FAIL')) return 'fail'
    return 'neutral'
}
