# 工作区布局

推荐把框架仓库和私有写作区分开。

```text
~/Projects/
├── webnovel-codex/
└── webnovel-workspace/
    ├── .codex/
    │   └── .webnovel-current-project
    ├── .env
    └── books/
        └── <book_slug>/
```

## 目录职责

- `webnovel-codex/`：脚本、dashboard、模板、文档、测试，可公开
- `webnovel-workspace/.env`：当前工作区共用的模型配置
- `webnovel-workspace/books/<book_slug>/`：单本书项目，里面放 `.webnovel/`、`正文/`、`大纲/`、`设定集/`
- `.codex/.webnovel-current-project`：当前书指针，`webnovel.py use` 会更新它

## 初始化一本书

```bash
python -X utf8 ~/Projects/webnovel-codex/webnovel-writer/scripts/webnovel.py init \
  ~/Projects/webnovel-workspace/books/<book_slug> \
  "小说标题" \
  "修仙"
```

初始化后，把当前书切到工作区指针：

```bash
python -X utf8 ~/Projects/webnovel-codex/webnovel-writer/scripts/webnovel.py use \
  ~/Projects/webnovel-workspace/books/<book_slug> \
  --workspace-root ~/Projects/webnovel-workspace
```

## 最小配置

工作区 `.env` 示例：

```bash
LLM_PROVIDER=openai_compatible
LLM_BASE_URL=https://api.mrxoad.uk/api/deepseek
LLM_CHAT_MODEL=deepseek-chat
LLM_REASONING_MODEL=deepseek-reasoner
DEEPSEEK_API_KEY=your_deepseek_api_key
API_GATEWAY_TOKEN=your_gateway_token
```

这套会先走官方 `DeepSeek API`，再把 `LLM_BASE_URL` 当后备。单本书有特殊模型时，再在书项目根目录单独写 `.env` 覆盖。

## 常用命令

```bash
python -X utf8 ~/Projects/webnovel-codex/webnovel-writer/scripts/webnovel.py --project-root ~/Projects/webnovel-workspace llm env-check
python -X utf8 ~/Projects/webnovel-codex/webnovel-writer/scripts/webnovel.py --project-root ~/Projects/webnovel-workspace llm draft --chapter 1
python -X utf8 ~/Projects/webnovel-codex/webnovel-writer/scripts/webnovel.py --project-root ~/Projects/webnovel-workspace llm review --chapter 1
python -m dashboard.server --project-root ~/Projects/webnovel-workspace --workspace-root ~/Projects/webnovel-workspace
```
