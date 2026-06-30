# Build python image
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install python dependencies
COPY pyproject.toml .
RUN pip install --no-cache-dir .

# Copy source code
COPY . .

EXPOSE 8000

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

CMD ["python", "dashboard/app.py"]
