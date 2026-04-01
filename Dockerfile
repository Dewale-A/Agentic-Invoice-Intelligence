# ============================================================
# AgenticInvoiceIntelligence - Multi-stage Dockerfile
# Stage 1: dependency builder
# Stage 2: lean runtime image
# ============================================================

# ----- Stage 1: builder -----
FROM python:3.11-slim AS builder

WORKDIR /build

# System dependencies for pdfplumber, pytesseract, and reportlab
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    tesseract-ocr \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt


# ----- Stage 2: runtime -----
FROM python:3.11-slim AS runtime

WORKDIR /app

# Runtime system libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY src/ ./src/
COPY run_server.py .
COPY .env.example .env.example

# Create data directory for SQLite persistence
RUN mkdir -p src/data

# Non-root user for security
RUN useradd -m -u 1001 appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
