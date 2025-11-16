FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Location for the uv-managed virtual environment (outside bind-mounted /app)
ENV UV_PROJECT_ENVIRONMENT=/opt/sim-doc/.venv

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

# Copy project files
COPY . .

# Install uv
RUN pip install uv

# Install Python dependencies
RUN uv sync --frozen --no-dev --no-cache

# Prevent uv from attempting to sync at runtime and ensure the venv is on PATH
ENV UV_NO_SYNC=1 \
    UV_FROZEN=1 \
    PATH="${UV_PROJECT_ENVIRONMENT}/bin:${PATH}"

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/api/v1/system/health || exit 1

# Default command
CMD ["uv", "run", "python", "main.py", "serve", "--host", "0.0.0.0"]
