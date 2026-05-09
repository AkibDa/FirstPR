FROM python:3.11-slim

# Install git for repo cloning
RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV VLLM_BASE_URL="http://vllm-server:8000/v1"
ENV CHROMA_DB_DIR="/app/chroma_db"

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]