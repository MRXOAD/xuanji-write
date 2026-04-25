# 前端重写说明

## 总体

- 旧的像素风界面已经移除。现在用深色 neutral gray 主题，主色是蓝色，PASS/WARN/FAIL 分别用绿、黄、红。
- `App.jsx` 改成页面路由和数据组合，公共表格、卡片、指标、热力图放到 `src/components/ui.jsx`。
- 图标改为线性 SVG React 组件，集中在 `src/components/icons.jsx`。本机无法联网安装 `lucide-react`，所以没有新增 npm 依赖。
- `index.css` 全部重写，主题变量放在 `:root` 和 `[data-theme="light"]`，右上角按钮切换深浅色。

## 6 个页面

1. `dashboard`
   - 顶部 4 个核心数字：当前章号、总字数、当前卷、质量状态。
   - 增加章节字数折线、LLM 调用统计、全本 audit 热力图、最近 5 章。
   - 本地运行面板保留 `use-book / env-check / prompt / draft / review`，但压缩到下方工具区。

2. `entities`
   - 表格列按 `id / canonical_name / type / tier / first_appearance / last_appearance` 展示。
   - 增加搜索、type 筛选、tier 筛选。
   - 点击实体后在右侧看当前状态和 state changes。

3. `graph`
   - 保留 `lazy()` 加载和 `react-force-graph-3d`。
   - 画布改成深色网格背景，右侧显示节点、关系、实体表和类型分布。
   - 只渲染有关联边的实体，避免孤立节点占用视野。

4. `chapters`
   - 左侧章节表更紧凑，右侧显示所选章节详情。
   - 单章详情包含 scenes、characters、hook、debt balance。
   - 保留单章 `/api/audit/{chapter}` 读取入口。

5. `files`
   - 左侧文件树，右侧只读预览。
   - 文件树使用线性图标，不再使用 emoji。
   - 预览区用固定高度和等宽字体，长文本可滚动。

6. `reading`
   - 把 reading-power、debts、overrides、invalid-facts 分成 4 个页签。
   - 顶部展示强 hook、未结债务、活跃 Override、无效事实 4 个数字。
   - 表格保留原接口字段，状态用语义色标识。
