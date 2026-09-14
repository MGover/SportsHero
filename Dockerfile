# Multi-stage: build streambot
FROM node:20-bookworm AS builder
WORKDIR /app

# Install build deps for native modules
RUN apt-get update && apt-get install -y python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy and build streambot
COPY streambot/package.json streambot/tsconfig.json streambot/patches ./streambot/
COPY streambot/src ./streambot/src
WORKDIR /app/streambot
RUN npm install
RUN npm run build

# Final image: node base with python installed
FROM node:20-bookworm-slim
WORKDIR /app

# Install python and ffmpeg for streaming
RUN apt-get update && apt-get install -y python3 python3-pip python3-venv ffmpeg \
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
