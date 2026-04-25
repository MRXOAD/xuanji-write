import { useEffect, useMemo, useRef, useState } from 'react'
import ForceGraph3D from 'react-force-graph-3d'
import { fetchJSON } from './api.js'
import { Network, RefreshCw } from './components/icons.jsx'
import { Button, EmptyState, PageHeader, Panel, StatusBadge } from './components/ui.jsx'

const TYPE_COLORS = {
    '角色': '#60a5fa',
    '地点': '#34d399',
    '星球': '#22d3ee',
    '神仙': '#f59e0b',
    '势力': '#a78bfa',
    '招式': '#f87171',
    '法宝': '#f472b6',
}

export default function GraphPage() {
    const [relationships, setRelationships] = useState([])
    const [entities, setEntities] = useState([])
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState('')
    const [dimensions, setDimensions] = useState({ width: 960, height: 620 })
    const shellRef = useRef(null)

    const load = () => {
        setLoading(true)
        setError('')
        Promise.all([
            fetchJSON('/api/relationships', { limit: 1000 }),
            fetchJSON('/api/entities'),
        ]).then(([rels, ents]) => {
            setRelationships(Array.isArray(rels) ? rels : [])
            setEntities(Array.isArray(ents) ? ents : [])
        }).catch(err => {
            setError(err instanceof Error ? err.message : String(err))
        }).finally(() => setLoading(false))
    }

    useEffect(() => {
        load()
    }, [])

    useEffect(() => {
        if (!shellRef.current) return
        const observer = new ResizeObserver(entries => {
            const rect = entries[0]?.contentRect
            if (!rect) return
            setDimensions({
                width: Math.max(360, Math.floor(rect.width)),
                height: Math.max(420, Math.floor(rect.height)),
            })
        })
        observer.observe(shellRef.current)
        return () => observer.disconnect()
    }, [])

    const graphData = useMemo(() => {
        const entityMap = new Map(entities.map(entity => [entity.id, entity]))
        const relatedIds = new Set()
        relationships.forEach(row => {
            if (row.from_entity) relatedIds.add(row.from_entity)
            if (row.to_entity) relatedIds.add(row.to_entity)
        })
        const nodes = [...relatedIds].map(id => {
            const entity = entityMap.get(id) || {}
            const tier = String(entity.tier || '').toUpperCase()
            return {
                id,
                name: entity.canonical_name || id,
                type: entity.type || '未知',
                tier: entity.tier || '-',
                val: tier === 'S' ? 10 : tier === 'A' ? 7 : tier === 'B' ? 5 : 3,
                color: TYPE_COLORS[entity.type] || '#94a3b8',
            }
        })
        const links = relationships
            .filter(row => row.from_entity && row.to_entity)
            .map(row => ({
                source: row.from_entity,
                target: row.to_entity,
                name: row.type || '关系',
                chapter: row.chapter,
                description: row.description,
            }))
        return { nodes, links }
    }, [entities, relationships])

    const typeCounts = useMemo(() => {
        const counts = new Map()
        graphData.nodes.forEach(node => counts.set(node.type, (counts.get(node.type) || 0) + 1))
        return [...counts.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8)
    }, [graphData.nodes])

    return (
        <>
            <PageHeader
                eyebrow="Graph"
                title="关系图谱"
                description="节点来自 entities，边来自 relationships。滚轮缩放，拖拽旋转。"
                actions={
                    <>
                        <StatusBadge tone={error ? 'fail' : loading ? 'warn' : 'primary'}>
                            {error ? '读取失败' : loading ? '加载中' : `${graphData.nodes.length} 节点 · ${graphData.links.length} 边`}
                        </StatusBadge>
                        <Button variant="secondary" icon={RefreshCw} onClick={load}>刷新</Button>
                    </>
                }
            />

            <div className="graph-page-grid">
                <Panel className="graph-panel">
                    <div className="graph-canvas" ref={shellRef}>
                        {graphData.nodes.length ? (
                            <ForceGraph3D
                                graphData={graphData}
                                width={dimensions.width}
                                height={dimensions.height}
                                nodeLabel={node => `${node.name} · ${node.type} · ${node.tier}`}
                                nodeColor={node => node.color}
                                nodeRelSize={5.5}
                                nodeResolution={16}
                                linkLabel={link => `${link.name}${link.chapter ? ` · 第 ${link.chapter} 章` : ''}`}
                                linkColor={() => 'rgba(148, 163, 184, 0.32)'}
                                linkWidth={1}
                                linkDirectionalParticles={1}
                                linkDirectionalParticleWidth={1.4}
                                linkDirectionalParticleSpeed={0.004}
                                backgroundColor="rgba(0,0,0,0)"
                                showNavInfo={false}
                                cooldownTicks={90}
                            />
                        ) : (
                            <EmptyState title={loading ? '加载图谱中' : '暂无关系图数据'} detail={error || 'relationships 为空'} />
                        )}
                    </div>
                </Panel>

                <Panel title="图谱摘要" meta="Top 类型分布">
                    <div className="graph-summary">
                        <MiniGraphStat label="节点" value={graphData.nodes.length} />
                        <MiniGraphStat label="关系" value={graphData.links.length} />
                        <MiniGraphStat label="实体表" value={entities.length} />
                    </div>
                    <div className="type-list">
                        {typeCounts.map(([type, count]) => (
                            <div key={type} className="type-row">
                                <span><i style={{ background: TYPE_COLORS[type] || '#94a3b8' }} />{type}</span>
                                <strong>{count}</strong>
                            </div>
                        ))}
                    </div>
                    <div className="graph-note">
                        <Network size={16} />
                        <span>只渲染有关系边的实体，避免孤点稀释视图。</span>
                    </div>
                </Panel>
            </div>
        </>
    )
}

function MiniGraphStat({ label, value }) {
    return (
        <div className="mini-stat">
            <span>{label}</span>
            <strong>{value}</strong>
        </div>
    )
}
