"""Webnovel Vibe Dashboard - 实时进度面板。

跑法:
  /opt/miniconda3/bin/streamlit run dashboard_vibe.py -- --project-root <BOOK_ROOT>

特性:
- 顶部:总进度条 + 卷号 + 字数
- 中部:LLM 调用统计 (latency / token / cost)
- 钩子类型分布饼图
- 最近章节卡片(标题+摘要预览)
- batch 跑批日志实时尾巴
- 5 秒自动刷新
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# 引入 audit + foreshadowing
sys.path.insert(0, str(Path(__file__).resolve().parent / "scripts"))
try:
    from draft_audit import audit as _audit_chapter
except Exception:
    _audit_chapter = None
try:
    from foreshadowing_tracker import list_open_foreshadowing as _list_foreshadowing
except Exception:
    _list_foreshadowing = None


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-root", required=True)
    args, _ = parser.parse_known_args(sys.argv[1:] if "--" not in sys.argv else sys.argv[sys.argv.index("--") + 1 :])
    return args


def _load_state(project_root: Path) -> dict:
    state_path = project_root / ".webnovel" / "state.json"
    if not state_path.is_file():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def _load_calls(project_root: Path, max_rows: int = 1000) -> pd.DataFrame:
    log_path = project_root / ".webnovel" / "logs" / "llm_calls.jsonl"
    if not log_path.is_file():
        return pd.DataFrame()
    rows = []
    with log_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows[-max_rows:])
    if "ts" in df.columns:
        df["ts_dt"] = pd.to_datetime(df["ts"], unit="s")
    if "usage" in df.columns:
        df["prompt_tokens"] = df["usage"].apply(lambda u: (u or {}).get("prompt_tokens", 0))
        df["completion_tokens"] = df["usage"].apply(lambda u: (u or {}).get("completion_tokens", 0))
        df["total_tokens"] = df["usage"].apply(lambda u: (u or {}).get("total_tokens", 0))
    else:
        df["prompt_tokens"] = 0
        df["completion_tokens"] = 0
        df["total_tokens"] = 0
    df["estimated_cost_usd"] = df.get("estimated_cost_usd", 0).fillna(0) if "estimated_cost_usd" in df.columns else 0
    return df


def _list_chapters(project_root: Path) -> list[dict]:
    text_dir = project_root / "正文"
    if not text_dir.is_dir():
        return []
    items = []
    pat = re.compile(r"^第(\d+)章-(.+)\.md$")
    for path in text_dir.glob("第*.md"):
        m = pat.match(path.name)
        if not m:
            continue
        items.append(
            {
                "chapter": int(m.group(1)),
                "title": m.group(2),
                "path": path,
                "size": path.stat().st_size,
                "mtime": path.stat().st_mtime,
            }
        )
    items.sort(key=lambda x: x["chapter"])
    return items


def _read_summary(project_root: Path, chapter: int) -> str:
    p = project_root / ".webnovel" / "summaries" / f"ch{chapter:04d}.md"
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8")[:600]


def _detect_hook_type(text: str) -> str:
    """根据章末段落粗判钩子类型(信息/谜题/动作/情绪/其他)。"""
    last = text[-300:] if len(text) > 300 else text
    if re.search(r"[?？]\s*$", last) or any(w in last for w in ["谁", "为什么", "怎么", "何时", "在哪"]):
        return "谜题钩"
    if any(w in last for w in ["举起", "推开", "拔出", "撞", "冲进", "追上", "跑", "拦", "扑"]):
        return "动作钩"
    if any(w in last for w in ["心头一紧", "脸色一变", "握紧", "深吸一口气", "心里", "想起", "记起"]):
        return "情绪钩"
    if any(w in last for w in ["发现", "看见", "看到", "认出", "记号", "字", "信", "册", "牌"]):
        return "信息钩"
    return "其他"


def _tail_batch_log(path: str = "/tmp/draft_log.txt", lines: int = 30) -> list[str]:
    p = Path(path)
    if not p.is_file():
        return []
    text = p.read_text(encoding="utf-8", errors="replace")
    return text.splitlines()[-lines:]


def main() -> None:
    args = _parse_args()
    project_root = Path(args.project_root)
    state = _load_state(project_root)
    calls = _load_calls(project_root)
    chapters = _list_chapters(project_root)

    st.set_page_config(page_title="Webnovel Vibe", layout="wide", page_icon="📖")
    st.title("📖 Webnovel Vibe")
    st.caption(f"project: {project_root}")

    # 自动刷新
    refresh_sec = st.sidebar.slider("自动刷新(秒)", 0, 30, 5)
    if refresh_sec > 0:
        st.sidebar.caption(f"下次刷新:{refresh_sec}s")
        st.sidebar.caption(f"现在:{datetime.now().strftime('%H:%M:%S')}")

    # ===== 顶部进度 =====
    progress = state.get("progress", {})
    project_info = state.get("project_info", {})
    current_ch = progress.get("current_chapter", 0)
    total_words = progress.get("total_words", 0)
    current_v = progress.get("current_volume", "?")
    completed = progress.get("volumes_completed", [])
    target_total = 800  # 全书目标 800 章

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("当前章", current_ch)
    c2.metric("目标章", target_total)
    c3.metric("总字数", f"{total_words:,}")
    c4.metric("当前卷", current_v)
    c5.metric("已完结卷", len(completed))

    pct = current_ch / target_total if target_total else 0
    st.progress(min(1.0, pct), text=f"进度 {pct:.1%}({current_ch}/{target_total})")

    st.divider()

    # ===== 章节字数曲线 =====
    if chapters:
        df_ch = pd.DataFrame(
            [{"chapter": c["chapter"], "size_kb": c["size"] / 1024, "title": c["title"]} for c in chapters]
        )
        fig = px.line(df_ch, x="chapter", y="size_kb", title="章节字节大小(kB)", markers=False, hover_data=["title"])
        fig.update_layout(height=240, margin=dict(t=40, b=20, l=10, r=10))
        st.plotly_chart(fig, use_container_width=True)

    # ===== LLM 调用统计 =====
    st.subheader("LLM 调用")
    if not calls.empty:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("调用次数", len(calls))
        col2.metric("成功率", f"{calls['success'].mean():.1%}" if "success" in calls else "—")
        if "latency_ms" in calls and calls["latency_ms"].notna().any():
            col3.metric("p50 latency", f"{calls['latency_ms'].quantile(0.5):.0f} ms")
            col4.metric("p95 latency", f"{calls['latency_ms'].quantile(0.95):.0f} ms")

        c5, c6, c7 = st.columns(3)
        c5.metric("prompt tokens", f"{int(calls['prompt_tokens'].sum()):,}")
        c6.metric("completion tokens", f"{int(calls['completion_tokens'].sum()):,}")
        if "estimated_cost_usd" in calls:
            c7.metric("估算成本", f"${calls['estimated_cost_usd'].sum():.4f}")

        # latency 分布
        if "latency_ms" in calls and calls["latency_ms"].notna().any():
            fig_lat = px.histogram(calls, x="latency_ms", nbins=30, title="latency 分布(ms)")
            fig_lat.update_layout(height=240, margin=dict(t=40, b=20, l=10, r=10))
            st.plotly_chart(fig_lat, use_container_width=True)

        # 按章 token 用量
        if "chapter" in calls and calls["total_tokens"].sum() > 0:
            df_by_ch = calls[calls["task"] == "draft"].groupby("chapter")["total_tokens"].sum().reset_index()
            if not df_by_ch.empty:
                fig_tok = px.bar(df_by_ch, x="chapter", y="total_tokens", title="每章 token 用量(draft)")
                fig_tok.update_layout(height=240, margin=dict(t=40, b=20, l=10, r=10))
                st.plotly_chart(fig_tok, use_container_width=True)
    else:
        st.info("暂无 LLM 调用日志")

    st.divider()

    # ===== 章节质量热力图 =====
    st.subheader("全本质量热力图(audit)")
    if _audit_chapter is not None and chapters:

        @st.cache_data(ttl=30)
        def _scan_all(root_str: str, ch_nums: tuple[int, ...]) -> list[dict]:
            root = Path(root_str)
            out = []
            for n in ch_nums:
                r = _audit_chapter(root, n)
                if r.get("found"):
                    out.append(r)
            return out

        ch_nums = tuple(c["chapter"] for c in chapters)
        audit_results = _scan_all(str(project_root), ch_nums)

        # status 编码:0=PASS, 1=PASS_WITH_WARN, 2=FAIL
        status_map = {"PASS": 0, "PASS_WITH_WARN": 1, "FAIL": 2}
        rows = []
        for r in audit_results:
            rows.append(
                {
                    "chapter": r["chapter"],
                    "status": status_map.get(r["verdict"], 0),
                    "verdict": r["verdict"],
                    "errors": r["errors"],
                    "warnings": r["warnings"],
                    "word_count": r["word_count"],
                }
            )
        df_audit = pd.DataFrame(rows)

        # 顶部摘要
        a1, a2, a3, a4 = st.columns(4)
        a1.metric("已扫", len(df_audit))
        a2.metric("PASS", int((df_audit["status"] == 0).sum()))
        a3.metric("WARN", int((df_audit["status"] == 1).sum()))
        a4.metric("FAIL", int((df_audit["status"] == 2).sum()))

        # 热力图:300 章按 20 列布局
        cols_per_row = 20
        n = len(df_audit)
        n_rows = (n + cols_per_row - 1) // cols_per_row
        grid_status = np.full((n_rows, cols_per_row), -1, dtype=float)
        grid_label = np.full((n_rows, cols_per_row), "", dtype=object)
        for i, row in df_audit.reset_index(drop=True).iterrows():
            r_i, c_i = divmod(i, cols_per_row)
            grid_status[r_i, c_i] = row["status"]
            grid_label[r_i, c_i] = (
                f"ch{int(row['chapter'])}<br>{row['verdict']}<br>"
                f"err={int(row['errors'])} warn={int(row['warnings'])}<br>字数 {int(row['word_count'])}"
            )

        # 用 plotly heatmap,3 色离散
        colorscale = [
            [0.0, "#3FB950"],  # PASS 绿
            [0.33, "#3FB950"],
            [0.34, "#D29922"],  # WARN 黄
            [0.66, "#D29922"],
            [0.67, "#F85149"],  # FAIL 红
            [1.0, "#F85149"],
        ]
        fig_heat = go.Figure(
            data=go.Heatmap(
                z=grid_status,
                text=grid_label,
                hovertemplate="%{text}<extra></extra>",
                colorscale=colorscale,
                zmin=0,
                zmax=2,
                showscale=False,
                xgap=2,
                ygap=2,
            )
        )
        fig_heat.update_layout(
            height=max(180, 28 * n_rows + 60),
            margin=dict(t=10, b=10, l=10, r=10),
            xaxis=dict(visible=False),
            yaxis=dict(autorange="reversed", visible=False),
        )
        st.plotly_chart(fig_heat, use_container_width=True)
        st.caption("绿 PASS / 黄 WARN / 红 FAIL,鼠标悬停看详情")

        # 失败章节明细
        fail_df = df_audit[df_audit["status"] == 2].sort_values("chapter")
        if not fail_df.empty:
            with st.expander(f"FAIL 章节明细({len(fail_df)})", expanded=False):
                # 按 chapter 取详细 issue
                fail_set = set(fail_df["chapter"].tolist())
                for r in audit_results:
                    if r["chapter"] not in fail_set:
                        continue
                    st.markdown(f"**ch{r['chapter']:04d}** (字数 {r['word_count']})")
                    for issue in r.get("issues", []):
                        if issue.get("level") == "error":
                            st.text(f"  ✗ {issue.get('msg', '')}")

        warn_df = df_audit[df_audit["status"] == 1].sort_values("chapter")
        if not warn_df.empty:
            with st.expander(f"WARN 章节明细({len(warn_df)})", expanded=False):
                warn_set = set(warn_df["chapter"].tolist())
                for r in audit_results:
                    if r["chapter"] not in warn_set:
                        continue
                    st.markdown(f"**ch{r['chapter']:04d}**")
                    for issue in r.get("issues", []):
                        if issue.get("level") == "warn":
                            st.text(f"  ⚠ {issue.get('msg', '')}")

    st.divider()

    # ===== 章末钩子分布 =====
    st.subheader("章末钩子分布(近 50 章)")
    recent_chapters = chapters[-50:] if len(chapters) > 50 else chapters
    hook_counts = {}
    for c in recent_chapters:
        text = c["path"].read_text(encoding="utf-8", errors="ignore")
        h = _detect_hook_type(text)
        hook_counts[h] = hook_counts.get(h, 0) + 1
    if hook_counts:
        df_hook = pd.DataFrame([{"type": k, "count": v} for k, v in hook_counts.items()])
        fig_hook = px.pie(df_hook, names="type", values="count", title=f"钩子类型(近 {len(recent_chapters)} 章)")
        fig_hook.update_layout(height=300, margin=dict(t=40, b=20, l=10, r=10))
        st.plotly_chart(fig_hook, use_container_width=True)

    st.divider()

    # ===== 最近章节卡片 =====
    st.subheader("最近 5 章")
    cols = st.columns(5)
    for col, c in zip(cols, chapters[-5:]):
        with col:
            st.markdown(f"**第{c['chapter']}章**")
            st.caption(c["title"])
            st.caption(f"{c['size'] / 1024:.1f} kB")
            mtime = datetime.fromtimestamp(c["mtime"]).strftime("%m-%d %H:%M")
            st.caption(mtime)
            summary = _read_summary(project_root, c["chapter"])
            if summary:
                with st.expander("摘要"):
                    st.text(summary[:300])

    st.divider()

    # ===== 未回收伏笔 =====
    st.subheader("未回收伏笔")
    if _list_foreshadowing is not None:
        try:
            open_items = _list_foreshadowing(project_root, max_age=20, current_chapter=current_ch)
        except Exception as exc:
            open_items = []
            st.caption(f"读取失败: {exc}")
        if open_items:
            f1, f2, f3 = st.columns(3)
            f1.metric("未回收数", len(open_items))
            ages = [int(x.get("age") or 0) for x in open_items]
            f2.metric("平均年龄(章)", f"{sum(ages) / len(ages):.0f}" if ages else 0)
            f3.metric("最老伏笔(章)", max(ages) if ages else 0)

            df_fs = pd.DataFrame(
                [
                    {
                        "planted_chapter": int(x.get("planted_chapter") or 0),
                        "age": int(x.get("age") or 0),
                        "content": str(x.get("content") or "")[:60],
                        "status": x.get("status", "?"),
                    }
                    for x in open_items
                ]
            )
            # 散点图:埋点章号 vs 年龄
            if len(df_fs) > 1:
                fig_fs = px.scatter(
                    df_fs,
                    x="planted_chapter",
                    y="age",
                    hover_data=["content"],
                    title="伏笔时间线(纵轴 = 距今多少章未推进)",
                    color="age",
                    color_continuous_scale="Reds",
                )
                fig_fs.update_layout(height=280, margin=dict(t=40, b=20, l=10, r=10))
                st.plotly_chart(fig_fs, use_container_width=True)
            with st.expander(f"全部未回收伏笔 ({len(open_items)})"):
                st.dataframe(df_fs, use_container_width=True, hide_index=True)
        else:
            st.caption("无超 20 章未推进的伏笔")
    else:
        st.caption("foreshadowing_tracker 未加载")

    st.divider()

    # ===== L2/L3 检查历史 =====
    st.subheader("L2/L3 检查历史")
    review_dir = project_root / "审查报告"
    if review_dir.is_dir():
        review_files = sorted(review_dir.glob("ch*.llm-review.md"))
        verifier_files = sorted(review_dir.glob("verify-*.md"))
        ch_count = len(review_files)
        v_count = len(verifier_files)
        v1, v2 = st.columns(2)
        v1.metric("机器审查报告(L2/L3)", ch_count)
        v2.metric("人工/verifier 报告", v_count)
        if review_files:
            with st.expander(f"机器审查报告 {ch_count}"):
                for f in review_files[-10:]:
                    st.text(f"  {f.name}  ({f.stat().st_size}B)")
        if verifier_files:
            with st.expander(f"verifier 报告 {v_count}"):
                for f in verifier_files[-10:]:
                    st.text(f"  {f.name}  ({f.stat().st_size}B)")
    else:
        st.caption("审查报告目录不存在")

    st.divider()

    # ===== batch 跑批日志 =====
    st.subheader("最近 batch 日志(/tmp/draft_log.txt)")
    log_lines = _tail_batch_log(lines=20)
    if log_lines:
        st.code("\n".join(log_lines), language="text")
    else:
        st.caption("无批量日志(还没跑过 batch_draft 或日志被清)")

    # ===== 设定集 =====
    with st.expander("项目元信息"):
        st.json(
            {
                "title": project_info.get("title"),
                "genre": project_info.get("genre"),
                "genre_composite": project_info.get("genre_composite"),
                "genre_profile_key": project_info.get("genre_profile_key"),
            }
        )

    # 自动刷新
    if refresh_sec > 0:
        time.sleep(refresh_sec)
        st.rerun()


if __name__ == "__main__":
    main()
