# Multi-stage: build streambot
FROM node:20-bullseye as builder
WORKDIR /app

# Install build deps for native modules
RUN apt-get update && apt-get install -y python3 make g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy and build streambot
COPY streambot/package.json streambot/tsconfig.json streambot/patches ./streambot/
COPY streambot/src ./streambot/src
WORKDIR /app/streambot
RUN npm ci
RUN npm run build

# Final image: node base with python installed
FROM node:20-bullseye-slim
WORKDIR /app

# Install python and ffmpeg for streaming
RUN apt-get update && apt-get install -y python3 python3-pip ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Copy built streambot
COPY --from=builder /app/streambot/dist ./streambot/dist
COPY --from=builder /app/streambot/node_modules ./streambot/node_modules
COPY streambot/package.json ./streambot/

# Copy python app
COPY requirements.txt ./
RUN pip3 install --no-cache-dir -r requirements.txt
COPY . .

ENV PYTHONUNBUFFERED=1

CMD ["python3", "sport-hero.py"]
