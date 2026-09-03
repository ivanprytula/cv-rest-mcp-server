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

RUN npm run build && ls -la dist/

# Dev stage: local docker-compose-watch stack ONLY (compose.yml's `spa`
# service builds `target: dev`) — never used for the deployed image. Runs
# Vite's own dev server so `develop.watch`'s `action: sync` (compose.yml)
# gives real HMR on save, same as running `npm run dev` natively. Branches
# off `builder` BEFORE its production `npm run build` above would matter
# for this stage — it never needs the built dist/, only node_modules — but
# must stay declared after that RUN in this file so builder's own build
# step isn't accidentally reassigned to this stage (Dockerfile instructions
# after `FROM x AS y` belong to y until the next FROM).
FROM builder AS dev
EXPOSE 5173
CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0", "--port", "5173"]

# Stage 2: minimal HTTP server
FROM node:24-alpine
WORKDIR /app
COPY --from=builder /app/frontend/dist ./public
COPY frontend/server.js ./server.js

RUN npm init -y && npm install --save express && echo "=== Contents of /app/public ===" && ls -la /app/public/ && echo "=== Contents of /app ===" && ls -la /app/

EXPOSE 8080
CMD ["node", "server.js"]
