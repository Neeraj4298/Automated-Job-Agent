FROM python:3.11-slim

# Install system dependencies for Playwright
RUN apt-get update && apt-get install -y \
    libglib2.0-0 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
    libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxcursor1 \
    libxdamage1 libxext6 libxfixes3 libxi6 libxrandr2 libxrender1 \
    libxss1 libxtst6 ca-certificates fonts-liberation libasound2 \
    libpangocairo-1.0-0 libpango-1.0-0 libgdk-pixbuf2.0-0 \
    libgtk-3-0 libgbm1 wget curl --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Playwright Chromium
RUN playwright install --with-deps chromium

# Copy project
COPY . .

# Create required directories
RUN mkdir -p screenshots logs queue/cookies reports/output

# Run the scheduler by default
CMD ["python", "main.py"]
