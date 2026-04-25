import { Suspense, lazy, useCallback, useEffect, useMemo, useState } from 'react'
import { fetchJSON, postJSON, subscribeSSE } from './api.js'
import {
    Activity,
    AlertTriangle,
    BookOpen,
    CheckCircle,
    Database,
    Eye,
    FileText,
    Files,
    Folder,
    FolderOpen,
    GitBranch,
    LayoutDashboard,
    Moon,
    Network,
    Play,
    RadioTower,
    RefreshCw,
    Search,
    Sun,
    Terminal,
    Users,
    XCircle,
    ChevronDown,
    ChevronRight,
} from './components/icons.jsx'
import {
    Button,
    DataTable,
    EmptyState,
    KeyValueList,
    MetricCard,
    PageHeader,
    Panel,
    ProgressBar,
    QualityHeatmap,
    SegmentedControl,
    Sparkline,
    StatusBadge,
    TextInput,
    auditTone,
    formatCell,
    formatNumber,
    formatPercent,
    pickNumber,
    toArray,
} from './components/ui.jsx'

const GraphPage = lazy(() => import('./GraphPage.jsx'))

const NAV_ITEMS = [
    { id: 'dashboard', label: '数据总览', icon: LayoutDashboard },
    { id: 'entities', label: '设定词典', icon: Users },
    { id: 'graph', label: '关系图谱', icon: Network },
    { id: 'chapters', label: '章节一览', icon: BookOpen },
    { id: 'files', label: '文档浏览', icon: Files },
    { id: 'reading', label: '追读力', icon: Activity },
]

export default function App() {
    const [page, setPage] = useState('dashboard')
    const [theme, setTheme] = useState(() => localStorage.getItem('dashboard-theme') || 'dark')
    const [projectInfo, setProjectInfo] = useState(null)
    const [refreshKey, setRefreshKey] = useState(0)
    const [connected, setConnected] = useState(false)
    const [loadError, setLoadError] = useState('')

    const loadProjectInfo = useCallback(() => {
        fetchJSON('/api/project/info')
            .then(data => {
                setProjectInfo(data)
                setLoadError('')
            })
            .catch(error => {
                setProjectInfo(null)
                setLoadError(error instanceof Error ? error.message : String(error))
            })
    }, [])

    useEffect(() => {
        document.documentElement.dataset.theme = theme
        localStorage.setItem('dashboard-theme', theme)
    }, [theme])

    useEffect(() => {
        loadProjectInfo()
    }, [loadProjectInfo, refreshKey])

    useEffect(() => {
        const unsub = subscribeSSE(
            () => setRefreshKey(key => key + 1),
            {
                onOpen: () => setConnected(true),
                onError: () => setConnected(false),
            },
        )
        return () => {
            unsub()
            setConnected(false)
        }
    }, [])

    const project = projectInfo?.project_info || {}
    const progress = projectInfo?.progress || {}
    const title = project.title || projectInfo?.title || '未加载项目'
    const currentPage = NAV_ITEMS.find(item => item.id === page)

    return (
        <div className="app-shell">
            <aside className="sidebar">
                <div className="brand">
                    <div className="brand-mark">WN</div>
                    <div>
                        <div className="brand-title">Webnovel Console</div>
                        <div className="brand-subtitle">{title}</div>
                    </div>
                </div>

                <nav className="nav-list" aria-label="主导航">
                    {NAV_ITEMS.map(item => {
                        const Icon = item.icon
                        return (
                            <button
                                key={item.id}
                                type="button"
                                className={`nav-button ${page === item.id ? 'active' : ''}`}
                                onClick={() => setPage(item.id)}
                            >
                                <Icon size={18} />
                                <span>{item.label}</span>
                            </button>
                        )
                    })}
                </nav>

                <div className="sidebar-footer">
                    <div className={`signal ${connected ? 'online' : 'offline'}`}>
                        <span />
                        {connected ? 'SSE 已连接' : 'SSE 断开'}
                    </div>
                    <div className="sidebar-meta">
                        <span>当前章</span>
                        <strong>{progress.current_chapter ? `第 ${progress.current_chapter} 章` : '-'}</strong>
                    </div>
                </div>
            </aside>

            <div className="workspace">
                <header className="topbar">
                    <div>
                        <div className="topbar-eyebrow">{currentPage?.label || 'Dashboard'}</div>
                        <div className="topbar-title">{title}</div>
                    </div>
                    <div className="topbar-actions">
                        {loadError ? <StatusBadge tone="fail">项目数据异常</StatusBadge> : null}
                        <Button variant="ghost" icon={RefreshCw} onClick={() => setRefreshKey(key => key + 1)}>刷新</Button>
                        <Button
                            variant="ghost"
                            icon={theme === 'dark' ? Sun : Moon}
                            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
                        >
                            {theme === 'dark' ? '浅色' : '深色'}
                        </Button>
                    </div>
                </header>

                <main className="main-content">
                    {page === 'dashboard' ? (
                        <DashboardPage state={projectInfo} refreshKey={refreshKey} onRefresh={() => setRefreshKey(key => key + 1)} />
                    ) : null}
                    {page === 'entities' ? <EntitiesPage refreshKey={refreshKey} /> : null}
                    {page === 'graph' ? (
                        <Suspense fallback={<GraphFallback />}>
                            <GraphPage key={refreshKey} />
                        </Suspense>
                    ) : null}
                    {page === 'chapters' ? <ChaptersPage refreshKey={refreshKey} /> : null}
                    {page === 'files' ? <FilesPage refreshKey={refreshKey} /> : null}
                    {page === 'reading' ? <ReadingPage refreshKey={refreshKey} /> : null}
                </main>
            </div>
        </div>
    )
}

function DashboardPage({ state, refreshKey, onRefresh }) {
    const [data, setData] = useState({
        chapters: [],
        toolStats: [],
        audit: { results: [], summary: {} },
        readingPower: [],
        reviewMetrics: [],
        checklistScores: [],
    })
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        let disposed = false
        setLoading(true)
        Promise.all([
            safeFetch('/api/chapters'),
            safeFetch('/api/tool-stats', { limit: 300 }),
            safeFetch('/api/audit'),
            safeFetch('/api/reading-power', { limit: 120 }),
            safeFetch('/api/review-metrics', { limit: 80 }),
            safeFetch('/api/checklist-scores', { limit: 160 }),
        ]).then(([chapters, toolStats, audit, readingPower, reviewMetrics, checklistScores]) => {
            if (disposed) return
            setData({
                chapters: toArray(chapters),
                toolStats: toArray(toolStats),
                audit: audit?.results ? audit : { results: [], summary: {} },
                readingPower: toArray(readingPower),
                reviewMetrics: toArray(reviewMetrics),
                checklistScores: toArray(checklistScores),
            })
            setLoading(false)
        })
        return () => {
            disposed = true
        }
    }, [refreshKey])

    if (!state) {
        return (
            <PageHeader
                eyebrow="Overview"
                title="数据总览"
                description="等待后端返回 state.json。"
            />
        )
    }

    const project = state.project_info || {}
    const progress = state.progress || {}
    const chapters = data.chapters
    const latestChapter = chapters.at(-1)
    const previousChapter = chapters.at(-2)
    const totalWords = Number(progress.total_words) || chapters.reduce((sum, row) => sum + (Number(row.word_count) || 0), 0)
    const targetWords = Number(project.target_words) || 0
    const progressPct = targetWords > 0 ? Math.min(100, (totalWords / targetWords) * 100) : 0
    const targetChapters = Number(project.target_chapters) || 0
    const chapterPct = targetChapters > 0 ? Math.min(100, ((Number(progress.current_chapter) || chapters.length) / targetChapters) * 100) : 0
    const volumeText = progress.current_volume ? `第 ${progress.current_volume} 卷` : '-'
    const wordDelta = latestChapter && previousChapter ? (Number(latestChapter.word_count) || 0) - (Number(previousChapter.word_count) || 0) : 0
    const wordSeries = chapters.slice(-80).map(row => Number(row.word_count) || 0)
    const nonZeroWordSeries = wordSeries.filter(value => value > 0)
    const recentChapters = [...chapters].slice(-5).reverse()
    const llmStats = computeToolStats(data.toolStats)
    const auditSummary = data.audit.summary || {}

    return (
        <>
            <PageHeader
                eyebrow="Overview"
                title="数据总览"
                description="章节进度、调用统计、质量热力图和最近章节集中在这一页。"
                actions={<StatusBadge tone={loading ? 'warn' : 'pass'}>{loading ? '加载中' : '数据已返回'}</StatusBadge>}
            />

            <div className="metric-grid">
                <MetricCard
                    label="当前章号"
                    value={progress.current_chapter || chapters.length || '-'}
                    unit="章"
                    sub={targetChapters ? `${formatPercent(chapterPct)} / ${targetChapters} 章` : '未设目标章数'}
                    tone="primary"
                />
                <MetricCard
                    label="总字数"
                    value={formatNumber(totalWords, { compact: true })}
                    sub={targetWords ? `${formatPercent(progressPct)} / ${formatNumber(targetWords, { compact: true })}` : '未设目标字数'}
                    trend={latestChapter ? { value: wordDelta, unit: '字' } : null}
                    tone="green"
                />
                <MetricCard
                    label="当前卷"
                    value={volumeText}
                    sub={project.genre || '题材未写入'}
                    tone="cyan"
                />
                <MetricCard
                    label="质量状态"
                    value={`${auditSummary.pass || 0}/${auditSummary.total || data.audit.results.length || 0}`}
                    sub={`WARN ${auditSummary.warn || 0} · FAIL ${auditSummary.fail || 0}`}
                    tone={auditSummary.fail > 0 ? 'red' : auditSummary.warn > 0 ? 'amber' : 'green'}
                />
            </div>

            <div className="dashboard-main-grid">
                <Panel title="章节字数走势" meta={`最近 ${wordSeries.length} 章`}>
                    <Sparkline values={wordSeries} />
                    <div className="chart-stat-row">
                        <span>最短 {formatNumber(nonZeroWordSeries.length ? Math.min(...nonZeroWordSeries) : 0)} 字</span>
                        <span>最长 {formatNumber(Math.max(...wordSeries, 0))} 字</span>
                        <span>均值 {formatNumber(average(wordSeries))} 字</span>
                    </div>
                </Panel>

                <Panel title="LLM 调用统计" meta="按 tool_call_stats 计算">
                    <div className="ops-stat-grid">
                        <MiniStat label="p50 latency" value={llmStats.p50 ? `${llmStats.p50} ms` : '-'} />
                        <MiniStat label="p95 latency" value={llmStats.p95 ? `${llmStats.p95} ms` : '-'} />
                        <MiniStat label="token" value={formatNumber(llmStats.tokens, { compact: true })} />
                        <MiniStat label="cost" value={llmStats.cost ? `$${llmStats.cost.toFixed(4)}` : '-'} />
                    </div>
                    <div className="success-meter">
                        <div>
                            <strong>{formatPercent(llmStats.successRate, 1)}</strong>
                            <span>成功率</span>
                        </div>
                        <ProgressBar value={llmStats.successRate} tone={llmStats.successRate >= 95 ? 'green' : 'amber'} />
                    </div>
                </Panel>

                <Panel title="全本质量热力图" meta={`${data.audit.results.length} 章 audit`}>
                    <QualityHeatmap results={data.audit.results.slice(-180)} />
                    <div className="legend-row">
                        <span><i className="dot pass" />PASS</span>
                        <span><i className="dot warn" />WARN</span>
                        <span><i className="dot fail" />FAIL</span>
                    </div>
                </Panel>

                <Panel title="最近 5 章" meta="按章节号倒序">
                    <DataTable
                        rows={recentChapters}
                        columns={[
                            { key: 'chapter', label: '章', render: value => `第 ${value} 章` },
                            { key: 'title', label: '标题', className: 'cell-strong' },
                            { key: 'word_count', label: '字数', render: value => formatNumber(value) },
                            { key: 'location', label: '地点' },
                        ]}
                        empty="暂无章节"
                    />
                </Panel>
            </div>

            <ActionPanel onRefresh={onRefresh} />
        </>
    )
}

function ActionPanel({ onRefresh }) {
    const [workspace, setWorkspace] = useState(null)
    const [selectedBook, setSelectedBook] = useState('')
    const [chapter, setChapter] = useState(1)
    const [targetWords, setTargetWords] = useState(2200)
    const [promptTask, setPromptTask] = useState('draft')
    const [running, setRunning] = useState('')
    const [result, setResult] = useState(null)

    const loadWorkspace = useCallback(() => {
        fetchJSON('/api/workspace/info')
            .then(payload => {
                setWorkspace(payload)
                setSelectedBook(prev => prev || payload?.project_root || '')
            })
            .catch(() => setWorkspace(null))
    }, [])

    useEffect(() => {
        loadWorkspace()
    }, [loadWorkspace])

    async function runAction(action, extra = {}) {
        const projectRoot = selectedBook || workspace?.project_root || ''
        setRunning(action)
        try {
            const payload = {
                project_root: projectRoot,
                chapter,
                target_words: targetWords,
                ...extra,
            }
            const response = await postJSON(`/api/actions/${action}`, payload)
            setResult({ action, ...response })
            if (action === 'use-book' && response?.workspace) {
                setWorkspace(response.workspace)
                setSelectedBook(response.workspace.project_root || projectRoot)
            }
            if (['use-book', 'draft', 'review', 'env-check'].includes(action)) {
                loadWorkspace()
                onRefresh()
            }
        } catch (error) {
            setResult({
                action,
                ok: false,
                exit_code: -1,
                stderr: error instanceof Error ? error.message : String(error),
            })
        } finally {
            setRunning('')
        }
    }

    const books = workspace?.books?.length ? workspace.books : [
        { path: workspace?.project_root || '', title: workspace?.current_title || '当前项目' },
    ]
    const llm = workspace?.llm || {}
    const missing = llm.missing_fields || []

    return (
        <Panel
            title="本地运行"
            meta="切书、环境检查、prompt、draft、review"
            actions={<StatusBadge tone={missing.length ? 'warn' : 'pass'}>{missing.length ? `缺 ${missing.length} 项配置` : 'LLM 可用'}</StatusBadge>}
            className="action-panel"
        >
            <div className="action-grid">
                <div className="form-block">
                    <label>
                        <span>书项目</span>
                        <select value={selectedBook} onChange={event => setSelectedBook(event.target.value)}>
                            {books.map(book => (
                                <option key={book.path || book.title} value={book.path || ''}>
                                    {book.title || book.path || '未命名'}
                                </option>
                            ))}
                        </select>
                    </label>
                    <Button icon={GitBranch} onClick={() => runAction('use-book')} disabled={!selectedBook || !!running}>
                        {running === 'use-book' ? '切换中' : '切换项目'}
                    </Button>
                </div>

                <div className="form-block two-cols">
                    <label>
                        <span>章节号</span>
                        <input type="number" min="1" value={chapter} onChange={event => setChapter(Number(event.target.value || 1))} />
                    </label>
                    <label>
                        <span>目标字数</span>
                        <input type="number" min="200" step="100" value={targetWords} onChange={event => setTargetWords(Number(event.target.value || 2200))} />
                    </label>
                    <label>
                        <span>Prompt 类型</span>
                        <select value={promptTask} onChange={event => setPromptTask(event.target.value)}>
                            <option value="draft">draft</option>
                            <option value="review">review</option>
                        </select>
                    </label>
                </div>

                <div className="action-buttons">
                    <Button variant="secondary" icon={Terminal} onClick={() => runAction('env-check')} disabled={!!running}>env-check</Button>
                    <Button variant="secondary" icon={FileText} onClick={() => runAction('prompt', { task: promptTask })} disabled={!!running}>prompt</Button>
                    <Button icon={Play} onClick={() => runAction('draft')} disabled={!!running}>{running === 'draft' ? 'draft 中' : 'draft'}</Button>
                    <Button variant="danger" icon={Eye} onClick={() => runAction('review')} disabled={!!running}>{running === 'review' ? 'review 中' : 'review'}</Button>
                </div>

                <div className="console-box">
                    {result ? (
                        <>
                            <div className="console-meta">
                                <StatusBadge tone={result.ok === false ? 'fail' : 'pass'}>{result.action}</StatusBadge>
                                <span>exit {result.exit_code ?? '-'}</span>
                            </div>
                            <pre>{result.payload ? JSON.stringify(result.payload, null, 2) : result.stdout || result.stderr || '无输出'}</pre>
                        </>
                    ) : (
                        <EmptyState title="暂无命令输出" detail="运行左侧动作后会显示 stdout / stderr" />
                    )}
                </div>
            </div>
        </Panel>
    )
}

function EntitiesPage({ refreshKey }) {
    const [entities, setEntities] = useState([])
    const [selected, setSelected] = useState(null)
    const [changes, setChanges] = useState([])
    const [query, setQuery] = useState('')
    const [typeFilter, setTypeFilter] = useState('all')
    const [tierFilter, setTierFilter] = useState('all')

    useEffect(() => {
        fetchJSON('/api/entities').then(rows => setEntities(toArray(rows))).catch(() => setEntities([]))
    }, [refreshKey])

    useEffect(() => {
        if (!selected) {
            setChanges([])
            return
        }
        fetchJSON('/api/state-changes', { entity: selected.id, limit: 40 })
            .then(rows => setChanges(toArray(rows)))
            .catch(() => setChanges([]))
    }, [selected])

    const types = useMemo(() => uniqueValues(entities, 'type'), [entities])
    const tiers = useMemo(() => uniqueValues(entities, 'tier'), [entities])
    const filtered = useMemo(() => {
        const q = query.trim().toLowerCase()
        return entities.filter(row => {
            if (typeFilter !== 'all' && row.type !== typeFilter) return false
            if (tierFilter !== 'all' && String(row.tier) !== tierFilter) return false
            if (!q) return true
            return [row.id, row.canonical_name, row.type, row.tier].some(value => String(value || '').toLowerCase().includes(q))
        })
    }, [entities, query, tierFilter, typeFilter])

    return (
        <>
            <PageHeader
                eyebrow="Entities"
                title="设定词典"
                description="按 id、名称、类型和层级检索实体，右侧查看状态变更。"
                actions={<StatusBadge tone="primary">{filtered.length} / {entities.length} 个实体</StatusBadge>}
            />

            <div className="toolbar">
                <TextInput icon={Search} placeholder="搜索 id / 名称 / type / tier" value={query} onChange={event => setQuery(event.target.value)} />
                <select value={typeFilter} onChange={event => setTypeFilter(event.target.value)}>
                    <option value="all">全部 type</option>
                    {types.map(type => <option key={type} value={type}>{type}</option>)}
                </select>
                <select value={tierFilter} onChange={event => setTierFilter(event.target.value)}>
                    <option value="all">全部 tier</option>
                    {tiers.map(tier => <option key={tier} value={tier}>{tier}</option>)}
                </select>
            </div>

            <div className="split-grid">
                <Panel title="实体表" meta="字段来自 entities">
                    <DataTable
                        rows={filtered}
                        rowKey={row => row.id}
                        activeKey={selected?.id}
                        onRowClick={setSelected}
                        pageSize={18}
                        columns={[
                            { key: 'id', label: 'id', className: 'mono-cell' },
                            { key: 'canonical_name', label: 'canonical_name', className: 'cell-strong' },
                            { key: 'type', label: 'type', render: value => <StatusBadge tone="primary">{value || '-'}</StatusBadge> },
                            { key: 'tier', label: 'tier' },
                            { key: 'first_appearance', label: 'first_appearance' },
                            { key: 'last_appearance', label: 'last_appearance' },
                        ]}
                    />
                </Panel>

                <Panel title={selected?.canonical_name || '实体详情'} meta={selected ? selected.id : '点击左侧实体'}>
                    {selected ? (
                        <>
                            <KeyValueList
                                items={[
                                    { label: 'type', value: selected.type },
                                    { label: 'tier', value: selected.tier },
                                    { label: 'first', value: selected.first_appearance },
                                    { label: 'last', value: selected.last_appearance },
                                    { label: 'archived', value: selected.is_archived ? 'true' : 'false' },
                                ]}
                            />
                            {selected.desc ? <p className="detail-text">{selected.desc}</p> : null}
                            {selected.current_json ? <pre className="json-block">{prettyJSON(selected.current_json)}</pre> : null}
                            <div className="subsection-title">状态变化</div>
                            <DataTable
                                rows={changes}
                                pageSize={8}
                                columns={[
                                    { key: 'chapter', label: '章' },
                                    { key: 'field', label: '字段' },
                                    { key: 'old_value', label: '旧值' },
                                    { key: 'new_value', label: '新值' },
                                ]}
                                empty="暂无状态变化"
                            />
                        </>
                    ) : (
                        <EmptyState title="未选择实体" detail="表格行支持点击查看详情" />
                    )}
                </Panel>
            </div>
        </>
    )
}

function ChaptersPage({ refreshKey }) {
    const [chapters, setChapters] = useState([])
    const [scenes, setScenes] = useState([])
    const [readingPower, setReadingPower] = useState([])
    const [selectedChapter, setSelectedChapter] = useState(null)
    const [audit, setAudit] = useState(null)
    const [auditLoading, setAuditLoading] = useState(false)

    useEffect(() => {
        Promise.all([
            safeFetch('/api/chapters'),
            safeFetch('/api/scenes', { limit: 1200 }),
            safeFetch('/api/reading-power', { limit: 300 }),
        ]).then(([chapterRows, sceneRows, readingRows]) => {
            const nextChapters = toArray(chapterRows)
            setChapters(nextChapters)
            setScenes(toArray(sceneRows))
            setReadingPower(toArray(readingRows))
            setSelectedChapter(prev => prev || nextChapters.at(-1)?.chapter || null)
        })
    }, [refreshKey])

    const selected = chapters.find(row => row.chapter === selectedChapter) || null
    const chapterScenes = scenes.filter(row => row.chapter === selectedChapter)
    const power = readingPower.find(row => row.chapter === selectedChapter)
    const totalWords = chapters.reduce((sum, row) => sum + (Number(row.word_count) || 0), 0)

    async function loadAudit() {
        if (!selectedChapter) return
        setAuditLoading(true)
        try {
            setAudit(await fetchJSON(`/api/audit/${selectedChapter}`))
        } catch (error) {
            setAudit({ found: false, verdict: 'ERROR', errors: [error instanceof Error ? error.message : String(error)] })
        } finally {
            setAuditLoading(false)
        }
    }

    return (
        <>
            <PageHeader
                eyebrow="Chapters"
                title="章节一览"
                description="左侧选章，右侧查看场景、出场角色、hook 和单章 audit。"
                actions={<StatusBadge tone="primary">{chapters.length} 章 · {formatNumber(totalWords, { compact: true })} 字</StatusBadge>}
            />

            <div className="split-grid wide-left">
                <Panel title="章节列表" meta="按 chapter 升序">
                    <DataTable
                        rows={chapters}
                        rowKey={row => row.chapter}
                        activeKey={selectedChapter}
                        onRowClick={row => {
                            setSelectedChapter(row.chapter)
                            setAudit(null)
                        }}
                        pageSize={22}
                        columns={[
                            { key: 'chapter', label: '章节', render: value => `第 ${value} 章` },
                            { key: 'title', label: '标题', className: 'cell-strong' },
                            { key: 'word_count', label: '字数', render: value => formatNumber(value) },
                            { key: 'location', label: '地点' },
                            { key: 'characters', label: 'characters', className: 'wide-cell' },
                        ]}
                    />
                </Panel>

                <Panel
                    title={selected ? `第 ${selected.chapter} 章` : '章节详情'}
                    meta={selected?.title || '未选择章节'}
                    actions={<Button variant="secondary" icon={Eye} onClick={loadAudit} disabled={!selectedChapter || auditLoading}>{auditLoading ? '读取中' : 'audit'}</Button>}
                >
                    {selected ? (
                        <>
                            <KeyValueList
                                items={[
                                    { label: '字数', value: formatNumber(selected.word_count) },
                                    { label: '地点', value: selected.location },
                                    { label: '角色', value: selected.characters },
                                    { label: 'hook_type', value: power?.hook_type },
                                    { label: 'hook_strength', value: power?.hook_strength },
                                    { label: 'debt_balance', value: power?.debt_balance },
                                ]}
                            />
                            <div className="subsection-title">场景</div>
                            <DataTable
                                rows={chapterScenes}
                                columns={[
                                    { key: 'scene_index', label: '序号' },
                                    { key: 'location', label: '地点' },
                                    { key: 'time', label: '时间' },
                                    { key: 'summary', label: 'summary', className: 'wide-cell' },
                                ]}
                                empty="暂无场景数据"
                            />
                            <div className="subsection-title">Audit</div>
                            {audit ? (
                                <div className={`audit-card audit-${auditTone(audit.verdict)}`}>
                                    <div>
                                        <strong>{audit.verdict || 'UNKNOWN'}</strong>
                                        <span>{audit.word_count ? `${audit.word_count} 字` : audit.found === false ? '未找到章节文本' : ''}</span>
                                    </div>
                                    {toArray(audit.errors).map((item, index) => <p key={`e-${index}`}>{item}</p>)}
                                    {toArray(audit.warnings).map((item, index) => <p key={`w-${index}`}>{item}</p>)}
                                </div>
                            ) : (
                                <EmptyState title="尚未读取 audit" detail="点击右上角 audit 获取单章报告" />
                            )}
                        </>
                    ) : (
                        <EmptyState title="暂无章节" />
                    )}
                </Panel>
            </div>
        </>
    )
}

function FilesPage({ refreshKey }) {
    const [tree, setTree] = useState({})
    const [selectedPath, setSelectedPath] = useState('')
    const [content, setContent] = useState('')
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        fetchJSON('/api/files/tree')
            .then(payload => {
                setTree(payload || {})
                const first = findFirstFilePath(payload || {})
                setSelectedPath(prev => prev || first || '')
            })
            .catch(() => setTree({}))
    }, [refreshKey])

    useEffect(() => {
        if (!selectedPath) return
        setLoading(true)
        fetchJSON('/api/files/read', { path: selectedPath })
            .then(payload => setContent(payload.content || ''))
            .catch(error => setContent(`[读取失败]\n${error instanceof Error ? error.message : String(error)}`))
            .finally(() => setLoading(false))
    }, [selectedPath])

    return (
        <>
            <PageHeader
                eyebrow="Files"
                title="文档浏览"
                description="只读预览正文、大纲和设定集。"
                actions={selectedPath ? <StatusBadge tone="primary">{selectedPath}</StatusBadge> : null}
            />

            <div className="file-grid">
                <Panel title="文件树" meta="正文 / 大纲 / 设定集">
                    <div className="tree-root">
                        {Object.entries(tree).map(([folder, items]) => (
                            <div key={folder} className="tree-section">
                                <div className="tree-section-title"><Folder size={15} />{folder}</div>
                                <TreeNodes items={items} selected={selectedPath} onSelect={setSelectedPath} />
                            </div>
                        ))}
                    </div>
                </Panel>

                <Panel title="内容预览" meta={loading ? '读取中' : selectedPath || '未选择文件'}>
                    {selectedPath ? (
                        <pre className="file-preview">{content || '文件为空'}</pre>
                    ) : (
                        <EmptyState title="未选择文件" />
                    )}
                </Panel>
            </div>
        </>
    )
}

function ReadingPage({ refreshKey }) {
    const [payload, setPayload] = useState({ readingPower: [], debts: [], overrides: [], invalidFacts: [], debtEvents: [] })
    const [tab, setTab] = useState('reading')

    useEffect(() => {
        Promise.all([
            safeFetch('/api/reading-power', { limit: 160 }),
            safeFetch('/api/debts', { limit: 160 }),
            safeFetch('/api/overrides', { limit: 160 }),
            safeFetch('/api/invalid-facts', { limit: 160 }),
            safeFetch('/api/debt-events', { limit: 200 }),
        ]).then(([readingPower, debts, overrides, invalidFacts, debtEvents]) => {
            setPayload({
                readingPower: toArray(readingPower),
                debts: toArray(debts),
                overrides: toArray(overrides),
                invalidFacts: toArray(invalidFacts),
                debtEvents: toArray(debtEvents),
            })
        })
    }, [refreshKey])

    const strongHooks = payload.readingPower.filter(row => String(row.hook_strength).toLowerCase() === 'strong').length
    const openDebts = payload.debts.filter(row => !['closed', 'done', 'resolved', '已关闭', '已解决'].includes(String(row.status).toLowerCase())).length
    const activeOverrides = payload.overrides.filter(row => !['closed', 'done', 'resolved', '已关闭', '已解决'].includes(String(row.status).toLowerCase())).length
    const invalidOpen = payload.invalidFacts.filter(row => !['closed', 'done', 'resolved', '已关闭', '已解决'].includes(String(row.status).toLowerCase())).length

    return (
        <>
            <PageHeader
                eyebrow="Reading"
                title="追读力"
                description="reading-power、债务、override 和无效事实集中查看。"
                actions={<SegmentedControl value={tab} onChange={setTab} items={[
                    { value: 'reading', label: '追读' },
                    { value: 'debts', label: '债务' },
                    { value: 'overrides', label: 'Override' },
                    { value: 'facts', label: '事实' },
                ]} />}
            />

            <div className="metric-grid compact">
                <MetricCard label="强 hook" value={strongHooks} unit="章" sub={`${payload.readingPower.length} 条记录`} tone="green" />
                <MetricCard label="未结债务" value={openDebts} unit="条" sub={`${payload.debts.length} 条债务`} tone={openDebts ? 'amber' : 'green'} />
                <MetricCard label="活跃 Override" value={activeOverrides} unit="条" sub={`${payload.overrides.length} 条合约`} tone={activeOverrides ? 'cyan' : 'green'} />
                <MetricCard label="无效事实" value={invalidOpen} unit="条" sub={`${payload.invalidFacts.length} 条记录`} tone={invalidOpen ? 'red' : 'green'} />
            </div>

            {tab === 'reading' ? (
                <Panel title="追读力数据" meta="chapter_reading_power">
                    <DataTable
                        rows={payload.readingPower}
                        pageSize={20}
                        columns={[
                            { key: 'chapter', label: '章节', render: value => `第 ${value} 章` },
                            { key: 'hook_type', label: 'hook_type' },
                            { key: 'hook_strength', label: 'hook_strength', render: value => <HookBadge value={value} /> },
                            { key: 'is_transition', label: 'transition', render: value => value ? 'true' : '-' },
                            { key: 'override_count', label: 'override' },
                            { key: 'debt_balance', label: 'debt_balance' },
                        ]}
                    />
                </Panel>
            ) : null}

            {tab === 'debts' ? (
                <Panel title="追读债务" meta="chase_debt + debt_events">
                    <DataTable
                        rows={payload.debts}
                        pageSize={20}
                        columns={[
                            { key: 'id', label: 'id' },
                            { key: 'debt_type', label: 'debt_type' },
                            { key: 'current_amount', label: 'amount' },
                            { key: 'interest_rate', label: 'rate' },
                            { key: 'due_chapter', label: 'due' },
                            { key: 'status', label: 'status', render: value => <StatusBadge tone={statusTone(value)}>{value || '-'}</StatusBadge> },
                        ]}
                    />
                </Panel>
            ) : null}

            {tab === 'overrides' ? (
                <Panel title="Override 合约" meta="override_contracts">
                    <DataTable
                        rows={payload.overrides}
                        pageSize={20}
                        columns={[
                            { key: 'chapter', label: 'chapter' },
                            { key: 'constraint_type', label: 'constraint_type' },
                            { key: 'constraint_id', label: 'constraint_id' },
                            { key: 'due_chapter', label: 'due' },
                            { key: 'status', label: 'status', render: value => <StatusBadge tone={statusTone(value)}>{value || '-'}</StatusBadge> },
                        ]}
                    />
                </Panel>
            ) : null}

            {tab === 'facts' ? (
                <Panel title="无效事实" meta="invalid_facts">
                    <DataTable
                        rows={payload.invalidFacts}
                        pageSize={20}
                        columns={[
                            { key: 'source_type', label: 'source_type' },
                            { key: 'source_id', label: 'source_id' },
                            { key: 'reason', label: 'reason', className: 'wide-cell' },
                            { key: 'status', label: 'status', render: value => <StatusBadge tone={statusTone(value)}>{value || '-'}</StatusBadge> },
                            { key: 'chapter_discovered', label: 'chapter' },
                        ]}
                    />
                </Panel>
            ) : null}
        </>
    )
}

function GraphFallback() {
    return (
        <>
            <PageHeader eyebrow="Graph" title="关系图谱" description="3D 图谱模块加载中。" />
            <Panel>
                <EmptyState title="加载 force-graph-3d" />
            </Panel>
        </>
    )
}

function TreeNodes({ items, selected, onSelect, depth = 0 }) {
    const [expanded, setExpanded] = useState({})
    if (!Array.isArray(items) || items.length === 0) return null

    return (
        <ul className={depth === 0 ? 'tree-list' : 'tree-list nested'}>
            {items.map((item, index) => {
                const key = item.path || `${depth}-${index}-${item.name}`
                if (item.type === 'dir') {
                    const open = expanded[key] ?? depth < 1
                    return (
                        <li key={key}>
                            <button type="button" className="tree-item" onClick={() => setExpanded(prev => ({ ...prev, [key]: !open }))}>
                                {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                                {open ? <FolderOpen size={15} /> : <Folder size={15} />}
                                <span>{item.name}</span>
                            </button>
                            {open ? <TreeNodes items={item.children} selected={selected} onSelect={onSelect} depth={depth + 1} /> : null}
                        </li>
                    )
                }
                return (
                    <li key={key}>
                        <button
                            type="button"
                            className={`tree-item file ${selected === item.path ? 'active' : ''}`}
                            onClick={() => onSelect(item.path)}
                        >
                            <span className="tree-spacer" />
                            <FileText size={15} />
                            <span>{item.name}</span>
                        </button>
                    </li>
                )
            })}
        </ul>
    )
}

function MiniStat({ label, value }) {
    return (
        <div className="mini-stat">
            <span>{label}</span>
            <strong>{value}</strong>
        </div>
    )
}

function HookBadge({ value }) {
    const text = value || '-'
    const lower = String(value || '').toLowerCase()
    const tone = lower.includes('strong') || lower.includes('高') ? 'pass' : lower.includes('weak') || lower.includes('低') ? 'fail' : 'warn'
    return <StatusBadge tone={tone}>{text}</StatusBadge>
}

function computeToolStats(rows) {
    const latencies = rows.map(row => pickNumber(row, ['latency_ms', 'duration_ms', 'elapsed_ms', 'latency'])).filter(Boolean).sort((a, b) => a - b)
    const successRows = rows.filter(row => row.success === 1 || row.success === true || String(row.success).toLowerCase() === 'true')
    const successRate = rows.length ? (successRows.length / rows.length) * 100 : 0
    const tokens = rows.reduce((sum, row) => sum + pickNumber(row, ['total_tokens', 'tokens', 'token_count', 'prompt_tokens']) + pickNumber(row, ['completion_tokens']), 0)
    const cost = rows.reduce((sum, row) => sum + pickNumber(row, ['cost_usd', 'cost', 'price_usd']), 0)
    return {
        p50: percentile(latencies, 50),
        p95: percentile(latencies, 95),
        successRate,
        tokens,
        cost,
    }
}

function percentile(values, pct) {
    if (!values.length) return 0
    const index = Math.min(values.length - 1, Math.max(0, Math.ceil((pct / 100) * values.length) - 1))
    return Math.round(values[index])
}

function average(values) {
    const nums = values.filter(value => Number.isFinite(Number(value))).map(Number)
    if (!nums.length) return 0
    return nums.reduce((sum, value) => sum + value, 0) / nums.length
}

function uniqueValues(rows, key) {
    return [...new Set(rows.map(row => row[key]).filter(value => value !== undefined && value !== null && value !== ''))].map(String).sort()
}

async function safeFetch(path, params) {
    try {
        return await fetchJSON(path, params)
    } catch {
        return Array.isArray(params) ? [] : null
    }
}

function findFirstFilePath(tree) {
    for (const items of Object.values(tree || {})) {
        const path = walkTree(items)
        if (path) return path
    }
    return ''
}

function walkTree(items) {
    if (!Array.isArray(items)) return ''
    for (const item of items) {
        if (item.type === 'file' && item.path) return item.path
        if (item.type === 'dir') {
            const child = walkTree(item.children)
            if (child) return child
        }
    }
    return ''
}

function prettyJSON(value) {
    try {
        return JSON.stringify(typeof value === 'string' ? JSON.parse(value) : value, null, 2)
    } catch {
        return formatCell(value)
    }
}

function statusTone(value) {
    const text = String(value || '').toLowerCase()
    if (['closed', 'done', 'resolved', '已关闭', '已解决', 'pass'].some(item => text.includes(item))) return 'pass'
    if (['fail', 'error', 'invalid', '过期'].some(item => text.includes(item))) return 'fail'
    if (['open', 'active', 'pending', 'warn', '进行'].some(item => text.includes(item))) return 'warn'
    return 'neutral'
}
