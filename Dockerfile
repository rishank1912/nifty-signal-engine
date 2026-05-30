# ─────────────────────────────────────────────────────────────
# Nifty 50 Signal Engine v4 — Docker Image
# Optimised for Railway · Render · Fly.io · AWS ECS · GCP Cloud Run
# ─────────────────────────────────────────────────────────────
FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc curl tzdata ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Set IST timezone so schedule fires at correct times
ENV TZ=Asia/Kolkata
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

WORKDIR /app

# Install Python deps first (better layer caching)
COPY nifty_api/requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY nifty_api/ .

# Create empty __init__ files so Python finds the packages
RUN touch strategies/__init__.py utils/__init__.py

# Expose port
EXPOSE 8000

# Health check — Docker will restart container if this fails
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# Run with uvicorn
CMD sh -c "python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"