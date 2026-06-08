FROM python:3.13-slim

WORKDIR /app

# Install deps first (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ backend/
COPY frontend/ frontend/
COPY prompts/ prompts/

# Copy soul static files (staged by sync-soul.sh)
COPY build_soul/ /soul_static/

# Copy startup script
COPY start-cloud.sh .
RUN chmod +x start-cloud.sh

EXPOSE 8787

CMD ["./start-cloud.sh"]
