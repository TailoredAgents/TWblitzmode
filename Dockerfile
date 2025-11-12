# VouchLink AI Prospecting System Docker Configuration

FROM python:3.11-slim

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1
ENV ENVIRONMENT=production

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements file
COPY requirements-production.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements-production.txt

# Copy application code
COPY agents/ agents/
COPY api/ api/
COPY src/ src/
COPY services/ services/
COPY security/ security/
COPY core/ core/
COPY integrations/ integrations/
COPY scripts/ scripts/
COPY config.py .
COPY run_vouchlink.py .
COPY run_server.py .
COPY start.sh .

# Ensure entrypoint script is executable
RUN chmod +x start.sh

# Create necessary directories
RUN mkdir -p data logs

# Set proper permissions
RUN useradd --create-home --shell /bin/bash app \
    && chown -R app:app /app
USER app

# Health check
HEALTHCHECK --interval=30s --timeout=30s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# Expose port
EXPOSE 8000

# Run the application
CMD ["bash", "start.sh"]
