const strokeProps = {
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.8,
    strokeLinecap: 'round',
    strokeLinejoin: 'round',
}

function IconBase({ children, size = 18, className = '', ...props }) {
    return (
        <svg
            viewBox="0 0 24 24"
            width={size}
            height={size}
            className={`icon ${className}`.trim()}
            aria-hidden="true"
            {...props}
        >
            {children}
        </svg>
    )
}

export function LayoutDashboard(props) {
    return (
        <IconBase {...props}>
            <rect x="3" y="3" width="7" height="8" rx="1.5" {...strokeProps} />
            <rect x="14" y="3" width="7" height="5" rx="1.5" {...strokeProps} />
            <rect x="14" y="12" width="7" height="9" rx="1.5" {...strokeProps} />
            <rect x="3" y="15" width="7" height="6" rx="1.5" {...strokeProps} />
        </IconBase>
    )
}

export function Users(props) {
    return (
        <IconBase {...props}>
            <path d="M16 19c0-2.2-1.8-4-4-4s-4 1.8-4 4" {...strokeProps} />
            <circle cx="12" cy="8" r="3" {...strokeProps} />
            <path d="M20 18c0-1.8-1.2-3.2-3-3.7" {...strokeProps} />
            <path d="M17 5.2a2.5 2.5 0 0 1 0 4.6" {...strokeProps} />
            <path d="M4 18c0-1.8 1.2-3.2 3-3.7" {...strokeProps} />
            <path d="M7 5.2a2.5 2.5 0 0 0 0 4.6" {...strokeProps} />
        </IconBase>
    )
}

export function Network(props) {
    return (
        <IconBase {...props}>
            <circle cx="6" cy="6" r="2.5" {...strokeProps} />
            <circle cx="18" cy="6" r="2.5" {...strokeProps} />
            <circle cx="12" cy="18" r="2.5" {...strokeProps} />
            <path d="M8.2 7.2 15.8 16.8" {...strokeProps} />
            <path d="M15.8 7.2 8.2 16.8" {...strokeProps} />
            <path d="M8.8 6h6.4" {...strokeProps} />
        </IconBase>
    )
}

export function BookOpen(props) {
    return (
        <IconBase {...props}>
            <path d="M4 5.5A3 3 0 0 1 7 4h5v16H7a3 3 0 0 0-3 1.5z" {...strokeProps} />
            <path d="M20 5.5A3 3 0 0 0 17 4h-5v16h5a3 3 0 0 1 3 1.5z" {...strokeProps} />
        </IconBase>
    )
}

export function Files(props) {
    return (
        <IconBase {...props}>
            <path d="M8 7h9l3 3v9a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2z" {...strokeProps} />
            <path d="M14 7v4h6" {...strokeProps} />
            <path d="M4 16V5a2 2 0 0 1 2-2h8" {...strokeProps} />
        </IconBase>
    )
}

export function Activity(props) {
    return (
        <IconBase {...props}>
            <path d="M3 12h4l2-6 4 12 2-6h6" {...strokeProps} />
        </IconBase>
    )
}

export function Database(props) {
    return (
        <IconBase {...props}>
            <ellipse cx="12" cy="5" rx="7" ry="3" {...strokeProps} />
            <path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5" {...strokeProps} />
            <path d="M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" {...strokeProps} />
        </IconBase>
    )
}

export function RadioTower(props) {
    return (
        <IconBase {...props}>
            <path d="M12 14v8" {...strokeProps} />
            <path d="M8 22h8" {...strokeProps} />
            <path d="M9 14h6l-3-6z" {...strokeProps} />
            <path d="M5.5 9.5a7 7 0 0 1 13 0" {...strokeProps} />
            <path d="M2.5 7.5a11 11 0 0 1 19 0" {...strokeProps} />
        </IconBase>
    )
}

export function Terminal(props) {
    return (
        <IconBase {...props}>
            <rect x="3" y="4" width="18" height="16" rx="2" {...strokeProps} />
            <path d="m7 9 3 3-3 3" {...strokeProps} />
            <path d="M13 15h4" {...strokeProps} />
        </IconBase>
    )
}

export function Search(props) {
    return (
        <IconBase {...props}>
            <circle cx="11" cy="11" r="7" {...strokeProps} />
            <path d="m16.5 16.5 4 4" {...strokeProps} />
        </IconBase>
    )
}

export function RefreshCw(props) {
    return (
        <IconBase {...props}>
            <path d="M20 11a8 8 0 0 0-14.4-4.8L4 8" {...strokeProps} />
            <path d="M4 4v4h4" {...strokeProps} />
            <path d="M4 13a8 8 0 0 0 14.4 4.8L20 16" {...strokeProps} />
            <path d="M20 20v-4h-4" {...strokeProps} />
        </IconBase>
    )
}

export function Moon(props) {
    return (
        <IconBase {...props}>
            <path d="M20 15.5A8.2 8.2 0 0 1 8.5 4a7 7 0 1 0 11.5 11.5z" {...strokeProps} />
        </IconBase>
    )
}

export function Sun(props) {
    return (
        <IconBase {...props}>
            <circle cx="12" cy="12" r="4" {...strokeProps} />
            <path d="M12 2v2" {...strokeProps} />
            <path d="M12 20v2" {...strokeProps} />
            <path d="m4.9 4.9 1.4 1.4" {...strokeProps} />
            <path d="m17.7 17.7 1.4 1.4" {...strokeProps} />
            <path d="M2 12h2" {...strokeProps} />
            <path d="M20 12h2" {...strokeProps} />
            <path d="m4.9 19.1 1.4-1.4" {...strokeProps} />
            <path d="m17.7 6.3 1.4-1.4" {...strokeProps} />
        </IconBase>
    )
}

export function ChevronRight(props) {
    return (
        <IconBase {...props}>
            <path d="m9 18 6-6-6-6" {...strokeProps} />
        </IconBase>
    )
}

export function ChevronDown(props) {
    return (
        <IconBase {...props}>
            <path d="m6 9 6 6 6-6" {...strokeProps} />
        </IconBase>
    )
}

export function Folder(props) {
    return (
        <IconBase {...props}>
            <path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" {...strokeProps} />
        </IconBase>
    )
}

export function FolderOpen(props) {
    return (
        <IconBase {...props}>
            <path d="M3 9V7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v1" {...strokeProps} />
            <path d="M4 10h17l-2 8a2 2 0 0 1-2 1.5H6a2 2 0 0 1-2-1.5z" {...strokeProps} />
        </IconBase>
    )
}

export function FileText(props) {
    return (
        <IconBase {...props}>
            <path d="M7 3h7l5 5v13H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2z" {...strokeProps} />
            <path d="M14 3v6h5" {...strokeProps} />
            <path d="M8 13h8" {...strokeProps} />
            <path d="M8 17h6" {...strokeProps} />
        </IconBase>
    )
}

export function CheckCircle(props) {
    return (
        <IconBase {...props}>
            <circle cx="12" cy="12" r="9" {...strokeProps} />
            <path d="m8 12.5 2.5 2.5L16.5 9" {...strokeProps} />
        </IconBase>
    )
}

export function AlertTriangle(props) {
    return (
        <IconBase {...props}>
            <path d="M10.5 4.5 2.8 18a2 2 0 0 0 1.7 3h15a2 2 0 0 0 1.7-3L13.5 4.5a1.7 1.7 0 0 0-3 0z" {...strokeProps} />
            <path d="M12 9v4" {...strokeProps} />
            <path d="M12 17h.01" {...strokeProps} />
        </IconBase>
    )
}

export function XCircle(props) {
    return (
        <IconBase {...props}>
            <circle cx="12" cy="12" r="9" {...strokeProps} />
            <path d="m9 9 6 6" {...strokeProps} />
            <path d="m15 9-6 6" {...strokeProps} />
        </IconBase>
    )
}

export function Play(props) {
    return (
        <IconBase {...props}>
            <path d="M8 5.5v13l11-6.5z" {...strokeProps} />
        </IconBase>
    )
}

export function GitBranch(props) {
    return (
        <IconBase {...props}>
            <circle cx="6" cy="5" r="2.5" {...strokeProps} />
            <circle cx="18" cy="6" r="2.5" {...strokeProps} />
            <circle cx="6" cy="19" r="2.5" {...strokeProps} />
            <path d="M6 7.5v9" {...strokeProps} />
            <path d="M8.2 17.8C13 16.5 16 12 16 8.5" {...strokeProps} />
        </IconBase>
    )
}

export function Eye(props) {
    return (
        <IconBase {...props}>
            <path d="M2.5 12s3.5-6 9.5-6 9.5 6 9.5 6-3.5 6-9.5 6-9.5-6-9.5-6z" {...strokeProps} />
            <circle cx="12" cy="12" r="2.5" {...strokeProps} />
        </IconBase>
    )
}
