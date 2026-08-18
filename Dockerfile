# ---- 构建层 ----
FROM python:3.12-slim AS builder
WORKDIR /app
ENV PIP_NO_CACHE_DIR=1
COPY pyproject.toml ./
COPY app ./app
RUN pip install --prefix=/install .

# ---- 运行层 ----
FROM python:3.12-slim
WORKDIR /app
COPY --from=builder /install /usr/local
COPY alembic.ini ./
COPY alembic ./alembic
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
