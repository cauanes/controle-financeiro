FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir uv==0.8.22
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/app ./app
COPY backend/migrations ./migrations
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
