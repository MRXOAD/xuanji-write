# 一镜像两用:fastapi 后端 + streamlit vibe 面板共享同一个 image
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

# 系统最小依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
        git curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先 copy requirements 利用 docker layer cache
COPY requirements.txt ./requirements.txt
COPY webnovel-writer/scripts/requirements.txt ./webnovel-writer/scripts/requirements.txt
COPY webnovel-writer/dashboard/requirements.txt ./webnovel-writer/dashboard/requirements.txt

RUN pip install --upgrade pip \
    && pip install -r requirements.txt \
    && pip install streamlit plotly pandas numpy

# 再 copy 源码
COPY . .

# 默认入口由 docker-compose 覆盖,这里给个保底
CMD ["python", "-c", "print('xuanji-write image ready. 用 docker-compose 起 fastapi/streamlit 服务。')"]
