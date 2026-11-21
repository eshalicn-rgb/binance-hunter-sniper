FROM python:3.14-slim

WORKDIR /app

# Install dependencies + Node.js (needed by pregainers.py radar via tools/market_rank.mjs)
RUN apt-get update && apt-get install -y --no-install-recommends curl gnupg && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y --no-install-recommends nodejs && \
    rm -rf /var/lib/apt/lists/* && \
    pip install flask requests

# Copy the hunter application
COPY . .

# Environment for unique port configuration
ENV HUNTER_PORT=4564
ENV BINANCE_API_KEY=""
ENV BINANCE_API_SECRET=""

# Expose the hunter dashboard port
EXPOSE 4564

# Command: run the Binance Hunter
CMD ["python", "app.py"]
