# Examples

这里放可以直接克隆起跑的 demo 书项目。**不放完整正文**,只放结构骨架 + 1-3 章示例 + 完整设定集。

## 目录

- [`demo-玄幻短篇/`](demo-玄幻短篇/) 修仙题材最简模板,3 章
- [`demo-民俗悬疑/`](demo-民俗悬疑/) 民俗悬疑题材模板,3 章(待补)
- [`demo-都市/`](demo-都市/) 都市题材模板(待补)

## 怎么用

```bash
# 1. 复制一份 demo 到自己的工作区
cp -r examples/demo-玄幻短篇 ~/Projects/webnovel-workspace/books/我的小说

# 2. 改 设定集/ 下的角色卡和题材锚点
# 3. 改 大纲/总纲.md
# 4. 写第 1 章大纲(在 大纲/第1章-XXX.md)
# 5. 跑
python webnovel-writer/scripts/webnovel.py llm draft --chapter 1
```

## 怎么贡献新 demo

新 demo 至少包含:
- `设定集/角色约束.md`(10-15 条)
- `设定集/角色语料白名单.md`(主要角色名单,每行一名)
- `大纲/总纲.md` + `大纲/前N章细纲.md`
- `大纲/阶段支架.md`(20-50 章一段的粗纲)
- `正文/` 至少 3 章示例
- `.webnovel/state.json`(用 init 生成)
- 该题材的 `transition_ranges.json`(如果有过渡期)

PR 标题格式:`add demo: <题材> <短描述>`
