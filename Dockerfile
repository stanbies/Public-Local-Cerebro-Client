FROM python:3.11-slim

WORKDIR /app

# Install system dependencies including OCR (Tesseract) for PDF text extraction
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libffi-dev \
    git \
    tesseract-ocr \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Install private Cerebro package using build argument
# CACHE_BUST changes on each build to force reinstall (gets latest version)
ARG GITHUB_TOKEN
ARG CACHE_BUST=1
RUN if [ -n "$GITHUB_TOKEN" ]; then \
    echo "Cache bust: $CACHE_BUST" && \
    pip install --no-cache-dir --upgrade git+https://${GITHUB_TOKEN}@github.com/stanbies/Cerebro_Algorithm_V2.git; \
    fi

# Copy application code
COPY . .

# Create data directory for persistent storage
RUN mkdir -p /app/data

# Expose the port
EXPOSE 18421

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CEREBRO_DATA_DIR=/app/data

# Run the application
CMD ["python", "main.py"]
