# Codex + 通用 LLM

这条路线不搬 Claude 的 `Skill/Agent` 壳，只复用项目状态、上下文和索引。

分工固定：

- `Codex` 管项目定位、上下文组装、章节回写、状态更新
- 外部 LLM 只负责正文草稿和审稿文本
- 第一版只支持 `OpenAI-compatible` 接口

## 配置位置

LLM 配置按这个顺序读取：

1. 进程环境变量
2. 书项目根目录 `.env`
3. 工作区根目录 `.env`
4. `~/.codex/webnovel-writer/.env`
5. `~/.claude/webnovel-writer/.env`

最小配置示例：

```bash
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.example.com/v1
LLM_CHAT_MODEL=your-chat-model
LLM_REASONING_MODEL=your-reasoning-model
LLM_API_KEY=your_api_key
```

如果你正文和审稿都用 `deepseek-chat / deepseek-reasoner`，现在默认顺序是：

1. 先打官方 `https://api.deepseek.com`
2. 官方失败后，再走你配置的 `LLM_BASE_URL`

最省事的写法是把官方 Key 和后备路由同时放着：

```bash
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.mrxoad.uk/api/deepseek
LLM_CHAT_MODEL=deepseek-chat
LLM_REASONING_MODEL=deepseek-reasoner
DEEPSEEK_API_KEY=your_deepseek_api_key
API_GATEWAY_TOKEN=your_gateway_token
```

如果你只想走官方，不要后备路由，就把 `LLM_BASE_URL` 直接写成官方地址：

```bash
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.deepseek.com
LLM_CHAT_MODEL=deepseek-chat
LLM_REASONING_MODEL=deepseek-reasoner
DEEPSEEK_API_KEY=your_deepseek_api_key
```

当前兼容的网关根路径有：

- `https://api.mrxoad.uk/api/openrouter`
- `https://api.mrxoad.uk/api/deepseek`
- `https://api.mrxoad.uk/api/siliconflow`
- `https://api.mrxoad.uk/api/volcengine`
- `https://api.mrxoad.uk/api/dashscope`

兼容说明：

- 旧的 `DEEPSEEK_*` 变量仍然能读
- 但新文档、面板和 CLI 都以 `LLM_*` 为主
- `deepseek-chat / deepseek-reasoner` 会优先尝试官方接口；其他模型仍按 `LLM_BASE_URL` 直接请求

## 核心命令

查配置：

```bash
python -X utf8 webnovel-writer/scripts/webnovel.py --project-root "<BOOK_ROOT>" llm env-check
```

先看 prompt：

```bash
python -X utf8 webnovel-writer/scripts/webnovel.py --project-root "<BOOK_ROOT>" llm prompt --chapter 12 --task draft
python -X utf8 webnovel-writer/scripts/webnovel.py --project-root "<BOOK_ROOT>" llm prompt --chapter 12 --task review
```

生成草稿：

```bash
python -X utf8 webnovel-writer/scripts/webnovel.py --project-root "<BOOK_ROOT>" llm draft --chapter 12
```

审稿：

```bash
python -X utf8 webnovel-writer/scripts/webnovel.py --project-root "<BOOK_ROOT>" llm review --chapter 12
```

兼容旧命令：

```bash
python -X utf8 webnovel-writer/scripts/webnovel.py --project-root "<BOOK_ROOT>" deepseek env-check
```

旧入口现在只是兼容别名，实际转发到同一套 `llm_adapter.py`。

## 产物与日志

- 草稿默认写到 `正文/`
- 审稿默认写到 `.webnovel/reviews/ch0012.llm-review.md`
- 写作与审稿的最小日志写到 `.webnovel/logs/llm_calls.jsonl`

草稿完成后会继续更新：

- `.webnovel/summaries/`
- `.webnovel/index.db`
- `.webnovel/state.json`
- `.webnovel/external_chapters.json`

## 工作区指针

工作区当前书项目优先写到：

- `WORKSPACE_ROOT/.codex/.webnovel-current-project`

如果工作区里也有 `.claude/`，会一起写：

- `WORKSPACE_ROOT/.claude/.webnovel-current-project`

用户级 registry 继续写到：

- `~/.codex/webnovel-writer/workspaces.json`
- `~/.claude/webnovel-writer/workspaces.json`
