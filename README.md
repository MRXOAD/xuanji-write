# xuanji-write

[![License](https://img.shields.io/badge/License-GPL%20v3-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)](https://www.python.org/)

中文长篇网文连续生成框架。一次性写完 300 章 / 106.7 万字,deepseek-chat 单章 28 秒,角色名/设定/伏笔不漂。

## 一句话讲做什么

用 LLM 写 800 章长篇网文,但**不让它忘**:角色名前后一致,反派死活不串,题材锚定不漂,伏笔超过 20 章自动提醒回收。配套实时进度面板能看到每章的钱、token、耗时和质量分。

## 实测数据

| | 数 |
|---|---|
| 已写 | 300 章 / 106.7 万字 |
| 单章生成 | 28 秒(deepseek-chat) |
| 单章成本 | $0.003-$0.01(看长度) |
| 全本 audit 扫一次 | 0.3 秒(300 章 × 7 类规则) |
| 角色名串稿率 | 0(全本统一,18 条角色锚点项目级覆盖) |
| 修仙词残留率 | 0(题材"民俗悬疑"不写"丹田/经脉",过渡期可豁免) |

## 跟同类项目的差异

| | xuanji-write | webnovel-writer 上游 v6.0 | AI_NovelGenerator | autonovel |
|---|---|---|---|---|
| 章末硬约束 audit + auto-retry | ✓ | ✗ | 部分 | ✗ |
| 多 LLM 路由 fallback | ✓(deepseek 官方→网关) | ✗ | ✗ | ✗ |
| 全本质量热力图 | ✓ | ✗ | ✗ | ✗ |
| token/cost 自动统计 | ✓ | ✗ | ✗ | ✗ |
| 角色言行风格库 | ✓(自动从历史抽) | ✗ | character_state | ✗ |
| 伏笔自动追踪 | ✓ | ✗ | ✗ | propagation debt |
| 长程上下文混合 | ✓(5 类来源) | ✓ | ✗ | ✓ |
| Story System 主合约 | 待补 | ✓ | ✗ | 五层共演化 |
| 多 agent 协作 | ✗ | ✗ | ✗ | ✓ |

## 安装

```bash
git clone https://github.com/<your-username>/xuanji-write.git
cd xuanji-write
python -m pip install -r requirements.txt
```

## 配置 LLM

最小配置(`.env`):

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
# 1. 初始化项目
python webnovel-writer/scripts/webnovel.py init --title "我的小说" --genre "民俗悬疑"

# 2. 写章节大纲(在 大纲/ 下放 第1章-XXX.md)
# 3. 跑 draft
python webnovel-writer/scripts/webnovel.py llm draft --chapter 1

# 4. 批量写
python webnovel-writer/scripts/webnovel.py llm batch-draft \
  --from-chapter 1 --to-chapter 20 --parallel 3 --skip-on-error

# 5. 实时面板
streamlit run webnovel-writer/dashboard_vibe.py -- --project-root ./books/我的小说
```

## 防漂的 7 层

写 800 章的难点是**不忘**。我们在 7 个地方堵 LLM:

1. **system prompt 角色锚点**(`设定集/角色约束.md`)— 项目级硬约束,自动注入
2. **大纲驱动**(`大纲/第NNN章-XXX.md`)— 强制每章有大纲,缺则降级到阶段支架
3. **长程上下文混合**— 近 2 章 + 卷头章 + 跨段锚点 + quest 主线 + 未回收伏笔的源章
4. **角色言行样本**— 从历史章自动抽该角色对白,挑 4 条注入 user prompt
5. **章末 audit 验证器**(`scripts/draft_audit.py`)— 7 类规则,失败自动 retry 一次
6. **三档检查模板**(`scripts/check_pipeline.py`)— L1 每章 / L2 段尾 / L3 卷尾
7. **伏笔自动追踪**(`scripts/foreshadowing_tracker.py`)— 写完一章自动提取,超 20 章未推进的回写到 prompt

详细方案:[`docs/long-term-consistency.md`](docs/long-term-consistency.md)

## 实时进度面板

```bash
streamlit run webnovel-writer/dashboard_vibe.py -- --project-root <BOOK>
```

8866 端口打开后能看:
- 顶部:总进度条 / 章号 / 字数 / 卷号
- 章节字节大小折线
- LLM 调用统计:p50/p95 latency / token / cost
- 全本质量热力图(20 列 × N 行,绿/黄/红)
- 章末钩子分布饼图
- 未回收伏笔散点图(纵轴 = 距今多少章)
- L2/L3 检查历史

另有 React dashboard 在 8000 端口(只读 30+ 端点)。

## 文档

- [`docs/architecture.md`](docs/architecture.md) 架构与模块
- [`docs/commands.md`](docs/commands.md) 命令详解
- [`docs/codex-llm.md`](docs/codex-llm.md) Codex 集成 + LLM 配置
- [`docs/rag-and-config.md`](docs/rag-and-config.md) RAG 索引
- [`docs/genres.md`](docs/genres.md) 题材模板
- [`docs/operations.md`](docs/operations.md) 运维和恢复
- [`docs/workspace.md`](docs/workspace.md) 工作区布局
- [`docs/long-term-consistency.md`](docs/long-term-consistency.md) 长周期一致性方案
- [`examples/`](examples/) demo 项目模板

## 致谢

- Fork 自 [`lingfengQAQ/webnovel-writer`](https://github.com/lingfengQAQ/webnovel-writer),保留 GPL v3 协议。
- 章末硬约束的设计思路借鉴了 autonovel 的 propagation debt。
- dashboard 的进度可视化参考了 wandb / mlflow 的指标面板。

## License

GPL v3(继承自上游)。详见 [LICENSE](LICENSE)。
