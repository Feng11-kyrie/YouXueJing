# 国内服务器拉不到 Docker Hub 时可覆盖：
#   docker compose build --build-arg PYTHON_IMAGE=docker.m.daocloud.io/library/python:3.12-slim
ARG PYTHON_IMAGE=python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates \
 && rm -rf /var/lib/apt/lists/*

COPY requirements-prod.txt .
# fastembed/onnxruntime 在个别 ARM 镜像上可能没有 wheel；装不上时降级为
# “翻译免费评分不可用”，不影响应用启动和 AI 精评。
RUN pip install --no-cache-dir nicegui==3.18.0 numpy==2.3.5 openai==3.29.0 \
 && (pip install --no-cache-dir fastembed==0.9.0 || echo "fastembed skipped")

COPY . .

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/login || exit 1

CMD ["python", "proto/app.py", "--port", "8080"]
