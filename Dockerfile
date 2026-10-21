FROM node:22-bookworm-slim AS frontend
WORKDIR /build
RUN npm install --global pnpm@11.25.0
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
COPY frontend/package.json ./frontend/package.json
RUN pnpm install --frozen-lockfile
COPY frontend ./frontend
RUN pnpm build

FROM python:3.11-slim-bookworm AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
COPY backend/requirements.txt backend/requirements-lock.txt ./backend/
RUN pip install -r backend/requirements.txt -c backend/requirements-lock.txt
COPY backend/app ./backend/app
COPY backend/admin.py backend/database.py ./backend/
COPY scripts/serve.py ./scripts/serve.py
COPY --from=frontend /build/frontend/dist ./frontend/dist
RUN useradd --create-home --uid 10001 community && mkdir -p backend/data && chown -R community:community /app
USER community
ENV APP_ENV=production COOKIE_SECURE=true
EXPOSE 10000
CMD ["python", "scripts/serve.py"]
