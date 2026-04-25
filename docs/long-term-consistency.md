# 长周期一致性设计

> 800 章 / 200 万字级别小说,LLM 怎么不漂。
> 当前现状 + 已实施 + 待实施 + 数据对比。

## 现状

写 300 章 106.7 万字测下来,LLM 漂的几个真实点:

| 漂法 | 例子 | 已有兜底 |
|---|---|---|
| 角色名混乱 | 主角 30-60 章被错改成"陈青/陈渊/陈灰" | system prompt 第 7 条 + audit 检测 |
| 设定崩坏 | 第 30 章写死的人 143 章又出现 | 角色约束.md 项目级覆盖 + audit 检测 |
| 死角色复活 | 第 30 章韩五尺被卷走 → 31 章街坊议论"死了" → 33 章独立断言"死了" | system prompt 第 8 条 + audit 检测 |
| 题材漂移 | 民俗悬疑写出"丹田/经脉/灵气" | system prompt + audit blacklist |
| 元信息漏字 | 章末写"章末钩子: ..." | audit `meta_leak` 检测 |
| 同名人物冲突 | 242 章把"祁照壁"误认为同名死者 | 大纲段落支架 + audit 抓"姓 X 大人" |
| 伏笔丢失 | 温会长 232-240 章在线后 60 章不出场 | 角色约束.md 标"未回收线索" |
| 钩子单一 | 28% 章节用情绪钩 | guidance hook_diversify 提示 |

## 当前已实施(可跑)

### 1. system prompt 三层

```
[通用规则]              ← BASE_WRITE_RULES (10 条)
[项目角色锚点]          ← 设定集/角色约束.md 加载(本书 18 条)
[本章大纲]              ← 大纲/第NNN章-XXX.md
[前文摘要]              ← 近 2 章摘要
[当前状态]              ← state.json 摘要
[写作提示]              ← guidance(钩子分散/爽点/题材锚定)
[RAG 线索]              ← 向量库召回(若启用)
```

### 2. audit 章末检测

`scripts/draft_audit.py`,7 类:
- 修仙词黑名单(过渡期降级)
- 修仙边缘词密度
- 元信息漏字
- 未知姓氏自造
- 字数异常
- 韩五尺写死
- 姐姐错名

`_sync_written_chapter` 写完自动跑,失败 stderr 告警。

### 3. audit retry

`cmd_draft` 检出 errors 时,把问题清单注入 user message 重生成一次。`--no-audit-retry` 关闭。

### 4. 角色约束.md 项目级覆盖

每条一行,自动注入到 system prompt。本书 18 条覆盖:
- 主角/官配/姐姐
- 主要角色身份不可换
- 反派死活状态
- 题材锚定(民俗悬疑非修仙)
- 已知"未回收线索"提醒

### 5. state 事务化

`_sync_written_chapter` 包装,失败回滚 state.json + external_chapters.json。

### 6. 卷规划自校准

`update_state.py --audit-volumes` 按 current_chapter 重算 current_volume / volumes_completed。

### 7. 全本 audit 热力图

streamlit 看板 0.3 秒扫 300 章,绿/黄/红三色一目了然。

---

## 待实施(按价值排序)

### A. 角色言行风格库(P0)

**问题**:LLM 知道"许三更说话偏冷",但写出来还是偏热。
**解法**:每个主要角色建一份"语料样本",从历史章节抽 10-20 条该角色的对白和动作描写,加权注入 system prompt。

```
设定集/语料库/许三更.md  ← 自动从正文抽取的高频对白和动作
设定集/语料库/沈见秋.md
设定集/语料库/韩五尺.md
```

**实现**:
- 新工具 `scripts/extract_character_voice.py`,扫全本提"<角色>: <对白>"或"<角色>说"前后 50 字
- 每章 draft 时,根据本章大纲里出现的角色名,从语料库挑 3-5 条样本注入 user prompt
- 每写 20 章自动刷新一次语料库

工作量:4-5h。

### B. 伏笔追踪表自动维护(P0)

**问题**:角色约束里靠人工标"温会长 60 章未出场",写到 800 章不可能全靠人工。
**解法**:自动从 state.json 的 `plot_threads.foreshadowing` 抽,但目前 LLM 不主动写 plot_threads。改成:

- 每章 draft 后,跑一次"伏笔提取"小 LLM 调用,提"本章引入的悬念"+"本章兑现的旧悬念"
- 写到 `state.json.plot_threads.foreshadowing[]`
- 下一章 draft 时,prompt 里注入"未回收伏笔(超 30 章未提及的)清单"

**实现**:
- 新工具 `scripts/extract_foreshadowing.py`(单独 LLM 调用,小模型也行)
- 接到 `_sync_written_chapter` 末尾
- 给 prompt builder 加 `render_open_foreshadowing(state, max_age=30)`

工作量:5-6h。

### C. OOC 检测(P1)

**问题**:角色言行漂得让读者出戏,但目前没机制检测。
**解法**:用 embedding 比对——本章该角色的对白向量化,跟历史向量库对比,余弦距离 > 阈值就警告。

**实现**:
- 把"角色对白"作为新一类 chunk 进 RAG 索引
- audit 加一项:本章该角色对白和历史平均对白的距离
- 距离 > 阈值 → warn,附上历史相似对白做对比

工作量:4-5h(依赖 RAG 已建好)。

### D. 长程上下文混合注入(P1)

**问题**:目前前文摘要只看近 2 章,跨卷伏笔/卷头主旨看不到。
**解法**:5 类摘要混合 inject:

```
[近 2 章摘要]            必须
[本卷卷头章摘要]         必须(让 LLM 记得本卷主题)
[最近 quest 主线章]      让主线不丢
[未回收伏笔的原始章摘要] 让伏笔有印象
[相似情境的历史章]       RAG 召回
```

**实现**:扩 `extract_chapter_context.select_previous_summaries()`,从 5 个维度选,各 1-2 个。

工作量:3-4h。

### E. 卷间转场 review(P1)

**问题**:240→241、260→261、280→281 这种段间衔接 LLM 容易"突兀切换"。
**解法**:每写完一段(20 章),自动跑一个 review,看跨段的人物关系/线索是否衔接。

**实现**:
- `scripts/segment_review.py`,读最后 5 章 + 下一段大纲首章
- LLM 单次调用判断衔接是否合理
- 接到 `cmd_batch_draft` 末尾,跨段时触发

工作量:3h。

### F. 三档自动检查模板(P2)

每章 draft 完跑三档:
- L1 audit(已有,正则,< 1 秒)
- L2 fact-check(用小 LLM,5-10 秒)
- L3 segment-review(每 20 章一次,30 秒)

按章号路由:
- 普通章:L1
- 段尾章(如 240/260/280):L1+L2
- 卷尾章(如 80/120/160):L1+L2+L3

工作量:2h(在 audit 基础上加)。

---

## 数据对比(改之前 vs 改之后)

| 指标 | 1-231 章(老 prompt) | 232-300 章(新 prompt) | 进一步措施 |
|---|---|---|---|
| 修仙词出现 | 21 处(集中前 60 章) | 0 处 | A+C 角色风格+OOC 检测 |
| 主角名串稿 | 60+ 章混乱 | 0 处 | system prompt 第 7 条已稳定 |
| 韩五尺死活 | 3 章硬冲突 | 0 处 | 角色约束.md 已锁定 |
| 钩子分布(情绪钩) | 偏多 | 13% 健康 | guidance 已生效 |
| 跨段衔接 bug | 未测 | 0 处 | E 自动加 review |
| 伏笔丢失 | 温会长 60 章 0 出现 | 同 | B 自动追踪 |

## 优先级建议

按"投入工作量 vs 产出"排序:

1. **B 伏笔追踪表**(5-6h)— 最影响读者体验,800 章不做就废
2. **A 角色言行风格库**(4-5h)— 直接提升每章质量
3. **D 长程上下文混合**(3-4h)— 投入小,改 1 个函数
4. **E 卷间转场 review**(3h)— 跨段不漂的关键
5. **F 三档检查模板**(2h)— 把 A-E 串起来
6. **C OOC 检测**(4-5h)— 依赖 RAG,后排

合计 21-25h。分 5 个迭代,每个迭代 4-5h 出一个能跑的版本。

## 不做的

- **不做**全章 LLM-as-judge(成本太高,跑 800 章烧钱)
- **不做**多 agent 协作生成(Cognition 红线:写文章不要让多个 agent 同时改同一文件)
- **不做**强制每章 retry 直到 PASS(可能死循环,LLM 不一定能改对)

## 关联文档

- `scripts/draft_audit.py` — L1 检测
- `scripts/llm_prompt_builder.py` — system prompt 组装
- `设定集/角色约束.md` — 项目级硬约束
- `.webnovel/transition_ranges.json` — 题材过渡期豁免
