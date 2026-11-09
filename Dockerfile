FROM python:3.11-slim

# Install system dependencies for Playwright & healthchecks
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 \
    libxdamage1 libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 \
    libxss1 libxtst6 ca-certificates fonts-liberation libasound2 \
    libpangocairo-1.0-0 libpango-1.0-0 libgdk-pixbuf2.0-0 \
    libgtk-3-0 libgbm1 wget curl --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium
RUN playwright install --with-deps chromium

# Copy project files (including frontend/ and server.py)
COPY . .

# Create persistent data directory for SQLite
RUN mkdir -p /app/data /app/reports/output

EXPOSE 8080

HEALTHCHECK --interval=20s --timeout=5s --retries=3 \
  CMD curl -fsS http://127.0.0.1:8080/api/health || exit 1

# Default command launches the unified Web Console + API + DB server
CMD ["python", "server.py", "--host", "0.0.0.0", "--port", "8080"]

