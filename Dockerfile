# Multi-stage: build streambot
FROM node:22-bookworm AS builder
WORKDIR /app

# Install build deps for native modules
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy and build streambot
COPY streambot/package.json streambot/package-lock.json streambot/tsconfig.json streambot/patches ./streambot/
COPY streambot/src ./streambot/src
WORKDIR /app/streambot
RUN npm ci
RUN npm run build

# Final image: node base with python installed
FROM node:22-bookworm-slim
WORKDIR /app

# Install python and ffmpeg for streaming
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends python3 python3-pip python3-venv ffmpeg libzmq5 \
    && rm -rf /var/lib/apt/lists/*

# Copy built streambot
COPY --from=builder /app/streambot/dist ./streambot/dist
COPY --from=builder /app/streambot/node_modules ./streambot/node_modules
COPY streambot/package.json ./streambot/

# Copy python app
COPY requirements.txt ./
RUN python3 -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python", "sport-hero.py"]
