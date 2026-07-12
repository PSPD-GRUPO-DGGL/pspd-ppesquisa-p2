# Build a partir da raiz do repositório:
#   docker build -f gateway/Dockerfile -t pspd/gateway:0.1.0 .

FROM node:20-slim

RUN useradd --create-home --uid 10001 pspd

WORKDIR /app/gateway

COPY gateway/package.json gateway/package-lock.json ./
RUN npm ci --omit=dev

COPY gateway/server.js gateway/instrumentation.js ./
COPY proto/ /app/proto/
COPY frontend/ /app/frontend/

USER pspd

EXPOSE 3000

ENV PORT=3000 \
    NODE_ENV=production

CMD ["node", "server.js"]
