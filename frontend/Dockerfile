# Multi-stage: build React SPA, serve via Node.js on Cloud Run
# Caching/compression handled by Cloud CDN + LB (not nginx).

# Stage 1: build frontend
FROM node:24-alpine AS builder
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build && ls -la dist/

# Stage 2: minimal HTTP server
FROM node:24-alpine
WORKDIR /app
COPY --from=builder /app/frontend/dist ./public
COPY frontend/server.js ./server.js

RUN npm init -y && npm install --save express && echo "=== Contents of /app/public ===" && ls -la /app/public/ && echo "=== Contents of /app ===" && ls -la /app/

EXPOSE 8080
CMD ["node", "server.js"]
