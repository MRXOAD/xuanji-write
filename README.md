# xuanji-write

[![License](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

中文长篇网文连续生成框架。这本书已经写到 300 章 / 106.7 万字,deepseek-chat 单章 28 秒。

![dashboard](docs/img/dashboard.png)

## 这工具解决什么问题

写长篇 LLM 容易忘:第 30 章死了的人第 143 章又出现,主角名字写到一半被改成另一个,本来是民俗悬疑写着写着冒出"丹田"。这框架在 7 个地方堵这种问题,每章生成完自动跑一次正则审查,出错就重来一次。

## 跑下来是什么样

| | 数 |
|---|---|
| 已写 | 300 章 / 106.7 万字 |
| 单章生成 | 28 秒(deepseek-chat) |
| 单章成本 | $0.003 - $0.01 |
| 全本审查 | 0.3 秒(300 章 × 7 类正则) |
| 跑了 69 章后失败章节 | 2 章(都是 API 断流,重跑成功) |
| 生成器代码量 | 2381 行 llm_adapter + 5 个独立工具 |

## 跟同类项目比

| | xuanji-write | webnovel-writer 上游 v6.0 | AI_NovelGenerator | autonovel |
|---|---|---|---|---|
| 章末规则审查 + 失败 retry | ✓ | ✗ | 部分 | ✗ |
| 多 LLM 路由 fallback | ✓ | ✗ | ✗ | ✗ |
| 全本质量热力图 | ✓ | ✗ | ✗ | ✗ |
| token / cost 自动统计 | ✓ | ✗ | ✗ | ✗ |
| 角色对白历史样本注入 | ✓ | ✗ | character_state | ✗ |
| 伏笔自动追踪 | ✓ | ✗ | ✗ | propagation debt |
| 长程上下文混合(5 类来源) | ✓ | ✓ | ✗ | ✓ |
| Story System 主合约 | ✗(待补) | ✓ | ✗ | 五层共演化 |
| 多 agent 协作 | ✗ | ✗ | ✗ | ✓ |

## 装

```bash
git clone https://github.com/MRXOAD/xuanji-write.git
cd xuanji-write
python -m pip install -r requirements.txt
```

## 配 LLM

`.env` 最小配置:

```bash
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.deepseek.com
LLM_CHAT_MODEL=deepseek-chat
LLM_REASONING_MODEL=deepseek-reasoner
DEEPSEEK_API_KEY=sk-xxx
```

支持网关回退、ModelScope embedding、Jina rerank。详见 [`docs/codex-llm.md`](docs/codex-llm.md)。

## 写第一本书

```bash
# 复制 demo 起步
cp -r examples/demo-都市悬疑 ~/.../books/我的悬疑
cd ~/.../books/我的悬疑

# 改设定集 / 角色约束.md 改成自己的角色
vim 设定集/角色约束.md

# 写第 1 章细纲到 大纲/第1章-XXX.md,然后跑
python webnovel-writer/scripts/webnovel.py llm draft --chapter 1

# 批量写 20 章,3 并发,失败跳过
python webnovel-writer/scripts/webnovel.py llm batch-draft \
  --from-chapter 1 --to-chapter 20 --parallel 3 --skip-on-error

# 实时面板
streamlit run webnovel-writer/dashboard_vibe.py -- --project-root .
```

## 7 层堵 LLM 跑偏

写到 800 章的难点不是写得快,是不让它忘。这框架堵 7 个口子:

1. **system prompt 项目级角色锚点** — 设定集/角色约束.md 每行一条,自动注入。换书改这一份
2. **大纲驱动** — 每章必须有 `大纲/第NNN章-XXX.md`,缺则自动从 `*阶段支架.md` 表格生成降级版
3. **长程上下文混合** — 近 2 章 + 卷头章 + 跨段锚点 + quest 主线 + 未回收伏笔的源章,5 类来源最多 5 章
4. **角色对白历史样本** — 从已写章节自动抽该角色的对白模式,挑 4 条注入(模仿语气不照抄)
5. **章末 audit 验证** — 7 类正则:修仙词 / 主角名串稿 / 元信息漏字 / 死活状态 / 字数异常 / 自造姓氏 / 姐姐错名
6. **失败自动 retry** — audit 检出 errors 时,把问题清单注入 user prompt 重生成一次
7. **伏笔自动追踪** — 每章写完用小 LLM 提"引入的悬念 + 兑现的旧悬念",超 20 章未推进的回写到下章 prompt

详见 [`docs/long-term-consistency.md`](docs/long-term-consistency.md)。

## 实时面板

```bash
streamlit run webnovel-writer/dashboard_vibe.py -- --project-root <BOOK>
```

8866 端口能看:
- 顶部:章号 / 字数 / 卷号 / 进度条
- 章节字节折线
- LLM 调用统计:p50/p95 latency / token / 估算成本
- 全本质量热力图 20×N(绿 = PASS / 黄 = WARN / 红 = FAIL)
- 章末钩子分布饼图(信息钩 / 谜题钩 / 动作钩 / 情绪钩)
- 未回收伏笔散点图(纵轴 = 距今多少章未推进)
- L2/L3 检查报告分类

另有 React dashboard 在 8000 端口(只读 30+ 端点,FastAPI + Vite + React 19)。

## CLI 速查

```bash
# 写作
webnovel.py llm draft --chapter 1                            # 单章,自带 audit retry
webnovel.py llm batch-draft --from-chapter 1 --to-chapter 20 --parallel 3 --skip-on-error
webnovel.py llm draft --chapter 1 --no-audit-retry           # 关 retry

# 检查
python scripts/draft_audit.py --project-root <BOOK> --chapter 250
python scripts/check_pipeline.py --project-root <BOOK> --chapter 240   # auto: L1/L2/L3
python scripts/llm_stats.py --project-root <BOOK> --by-task            # token + cost

# 维护
python scripts/extract_character_voice.py --project-root <BOOK>        # 刷新角色样本
python scripts/foreshadowing_tracker.py --project-root <BOOK> --list-open --max-age 30

# state 修
python scripts/update_state.py --project-root <BOOK> --set-genre "民俗悬疑"
python scripts/update_state.py --project-root <BOOK> --audit-volumes   # 卷号自校准

# RAG
python scripts/data_modules/rag_adapter.py --project-root <BOOK> rebuild-all
```

## examples

- [`examples/demo-玄幻短篇/`](examples/demo-玄幻短篇/) 修仙模板,沈砚之/青鸾宗,3 章细纲
- [`examples/demo-都市悬疑/`](examples/demo-都市悬疑/) 现代连环案,陈晓白/网约车,**带 3 章实跑正文**

## 文档

- [`docs/architecture.md`](docs/architecture.md) 架构与模块
- [`docs/commands.md`](docs/commands.md) 命令详解
- [`docs/codex-llm.md`](docs/codex-llm.md) Codex 集成 + LLM 配置
- [`docs/rag-and-config.md`](docs/rag-and-config.md) RAG 索引
- [`docs/genres.md`](docs/genres.md) 题材模板
- [`docs/operations.md`](docs/operations.md) 运维和恢复
- [`docs/workspace.md`](docs/workspace.md) 工作区布局
- [`docs/long-term-consistency.md`](docs/long-term-consistency.md) 长周期一致性方案

## 致谢

Fork 自 [`lingfengQAQ/webnovel-writer`](https://github.com/lingfengQAQ/webnovel-writer),保留 GPL v3。
章末规则审查思路借鉴 autonovel 的 propagation debt。
dashboard 进度可视化参考 wandb / mlflow。

## License

GPL v3,继承自上游。详见 [LICENSE](LICENSE)。
