FROM python:3.12-slim

# Install Playwright system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium + all its system dependencies in one step
RUN playwright install --with-deps chromium

COPY . .

EXPOSE 8000

# Run migrations then start the server
CMD alembic upgrade head && \
    uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
