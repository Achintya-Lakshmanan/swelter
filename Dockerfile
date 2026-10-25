# ChillySOS server for Vultr (or any Docker host): web demo + iPhone app API.
#   docker build -t swelter . && docker run -p 8000:8000 --env-file .env swelter
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /bin/uv
WORKDIR /srv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra tiger
COPY server.py ./
COPY backend ./backend
COPY app ./app
ENV HOST=0.0.0.0 PORT=8000
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "server.py"]
