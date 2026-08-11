FROM python:3.11-slim

WORKDIR /app

# Install system dependencies required by your stack (psycopg2, cryptography, weasyprint, etc.)
# ✅ ADDED: chromium + fonts so pyppeteer can launch a real browser on Render.
# NOTE: libgdk-pixbuf-xlib-2.0-0 replaces libgdk-pixbuf2.0-0 in Debian Trixie+
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    libffi-dev \
    libcairo2 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libgdk-pixbuf-xlib-2.0-0 \
    shared-mime-info \
    libmagic1 \
    chromium \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for Docker layer caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Copy startup script and make it executable
COPY start.sh /app/start.sh
RUN chmod +x /app/start.sh

# Create a non-root user for security
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Render will override this with the $PORT env var
EXPOSE 8000

# Run the startup script
CMD ["/app/start.sh"]
