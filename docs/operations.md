# 项目结构与运维

## 目录层级（真实运行）

在 `webnovel-codex` 的推荐布局里，至少有 4 层概念：

1. `WORKSPACE_ROOT`（私有写作工作区，推荐 `~/Projects/webnovel-workspace`）
2. `WORKSPACE_ROOT/.codex/`（工作区级当前书指针）
3. `PROJECT_ROOT`（真实小说项目根，推荐 `WORKSPACE_ROOT/books/<book_slug>`）
4. `FRAMEWORK_ROOT`（公开框架仓库，推荐 `~/Projects/webnovel-codex`）

### A) Workspace 目录（含 `.codex`）

```text
workspace-root/
├── .codex/
│   └── .webnovel-current-project   # 指向当前小说项目根
├── .env
└── books/
    ├── 小说A/
    └── 小说B/
```

### B) 小说项目目录（`PROJECT_ROOT`）

```text
project-root/
├── .webnovel/            # 运行时数据（state/index/vectors/summaries）
├── 正文/                  # 正文章节
├── 大纲/                  # 总纲与卷纲
└── 设定集/                # 世界观、角色、力量体系
```

## 框架仓库目录

框架仓库不在小说项目目录内，运行命令时从 `FRAMEWORK_ROOT` 调外部书项目：

```text
${FRAMEWORK_ROOT}/
├── webnovel-writer/
│   ├── dashboard/
│   ├── scripts/
│   ├── skills/
│   └── templates/
└── docs/
```

### C) 用户级全局映射（兜底）

当工作区没有可用指针时，会使用用户级 registry 做 `workspace -> current_project_root` 映射：

```text
~/.codex/webnovel-writer/workspaces.json
~/.claude/webnovel-writer/workspaces.json
```

## 模拟目录实测（2026-03-03）

基于 `D:\wk\novel skill\plugin-sim-20260303-012048` 的实际结果：

- `WORKSPACE_ROOT`：`D:\wk\novel skill\plugin-sim-20260303-012048`
- 指针文件：`D:\wk\novel skill\plugin-sim-20260303-012048\.claude\.webnovel-current-project`
- 指针内容：`D:\wk\novel skill\plugin-sim-20260303-012048\凡人资本论-二测`
- 已创建项目示例：`凡人资本论/`、`凡人资本论-二测/`

## 常用运维命令

统一前置（手动 CLI 场景）：

```bash
export FRAMEWORK_ROOT="$HOME/Projects/webnovel-codex"
export WORKSPACE_ROOT="$HOME/Projects/webnovel-workspace"
export SCRIPTS_DIR="${FRAMEWORK_ROOT}/webnovel-writer/scripts"
export PROJECT_ROOT="$(python "${SCRIPTS_DIR}/webnovel.py" --project-root "${WORKSPACE_ROOT}" where)"
```

### 索引重建

```bash
python "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" index process-chapter --chapter 1
python "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" index stats
```

### 健康报告

```bash
python "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" status -- --focus all
python "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" status -- --focus urgency
```

### 向量重建

```bash
python "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" rag index-chapter --chapter 1
python "${SCRIPTS_DIR}/webnovel.py" --project-root "${PROJECT_ROOT}" rag stats
```

### 测试入口

```bash
pwsh "${SCRIPTS_DIR}/run_tests.ps1" -Mode smoke
pwsh "${SCRIPTS_DIR}/run_tests.ps1" -Mode full
```
