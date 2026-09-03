# Multi-stage: build React SPA, serve via Node.js on Cloud Run
# Caching/compression handled by Cloud CDN + LB (not nginx).

# Stage 1: build frontend
FROM node:24-alpine AS builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./

# Vite bakes import.meta.env.VITE_* into the JS bundle at build time — there
# is no runtime injection for a compiled SPA (unlike api-core's env_vars,
# which the running container reads via os.environ). Build-arg is named for
# the service it targets (matches api-core's PORTFOLIO_BASE_URL naming, and
# leaves room for a future GAMES_BASE_URL equivalent if games.* ever gets a
# UI); Vite itself still requires the VITE_ prefix to expose it at runtime.
# Default matches frontend/.env.example for a plain `docker build` with no
# arg supplied.
ARG PORTFOLIO_BASE_URL=http://localhost:8080
ENV VITE_API_BASE_URL=$PORTFOLIO_BASE_URL

RUN npm run build

# Local dev's watch-mode SPA container uses Dockerfile.spa instead of a
# stage here — keeps this file CI/CD-only (build-once, deploy-as-is), so a
# local-dev-only stage can never again silently break the production build
# (see git history: a `dev` stage inserted here once did exactly that).

# Stage 2: minimal HTTP server
FROM node:24-alpine
WORKDIR /app
COPY --from=builder /app/frontend/dist ./public
COPY frontend/server.js ./server.js

RUN npm init -y && npm install --save express

EXPOSE 8080
CMD ["node", "server.js"]
