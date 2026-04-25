# RAG 与配置说明

## RAG 检索架构

```text
查询 → QueryRouter(auto) → vector / bm25 / hybrid / graph_hybrid
                     └→ RRF 融合 + Rerank → Top-K
```

默认模型：

- Embedding：`Qwen/Qwen3-Embedding-8B`
- Reranker：`jina-reranker-v3`

## 环境变量加载顺序

1. 进程环境变量（最高优先级）
2. 书项目根目录下的 `.env`
3. 工作区根目录下的 `.env`
4. 用户级全局：`~/.codex/webnovel-writer/.env`
5. 用户级全局：`~/.claude/webnovel-writer/.env`

## `.env` 最小配置

```bash
EMBED_BASE_URL=https://api-inference.modelscope.cn/v1
EMBED_MODEL=Qwen/Qwen3-Embedding-8B
EMBED_API_KEY=your_embed_api_key

RERANK_BASE_URL=https://api.jina.ai/v1
RERANK_MODEL=jina-reranker-v3
RERANK_API_KEY=your_rerank_api_key

LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.mrxoad.uk/api/deepseek
LLM_CHAT_MODEL=deepseek-chat
LLM_REASONING_MODEL=deepseek-reasoner
DEEPSEEK_API_KEY=your_deepseek_api_key
API_GATEWAY_TOKEN=your_gateway_token
```

说明：

- 未配置 Embedding Key 时，语义检索会回退到 BM25。
- 推荐把每本书的差异配置写到 `${PROJECT_ROOT}/.env`，共用配置写到 `${WORKSPACE_ROOT}/.env`。
- 旧的 `DEEPSEEK_*` 变量仍然兼容，但新入口统一用 `LLM_*`。
- `deepseek-chat / deepseek-reasoner` 默认先打官方 `https://api.deepseek.com`，失败后再走 `LLM_BASE_URL`。
