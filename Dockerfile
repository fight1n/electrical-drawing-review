FROM python:3.11-slim

WORKDIR /app

# System deps for optional native parsers
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libgl1 libglib2.0-0 && rm -rf /var/lib/apt/lists/*

COPY requirements.txt requirements-llm.txt ./
RUN pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r requirements-llm.txt || true

COPY . .
RUN pip install --no-cache-dir -e .

EXPOSE 8000
ENV EDR_LLM_PROVIDER=mock
CMD ["uvicorn", "edr.api:app", "--host", "0.0.0.0", "--port", "8000"]
