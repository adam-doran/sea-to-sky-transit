# One image for the collector, replay and API (choose with the command).
# Build from the repository root:  docker build -f backend/Dockerfile .
FROM python:3.13-slim

COPY --from=ghcr.io/astral-sh/uv:0.11.14 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv \
    PATH=/app/.venv/bin:$PATH \
    TRANSITLIVE_CONFIG=/app/config/systems.toml \
    PYTHONUNBUFFERED=1

WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
COPY config /app/config
COPY LICENSE /app/LICENSE
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 transitlive && mkdir -p /archive && chown transitlive /archive
USER transitlive
ENTRYPOINT ["transitlive"]
CMD ["--help"]
