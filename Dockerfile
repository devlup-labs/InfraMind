FROM python:3.11-slim

WORKDIR /app

ARG TARGETPLATFORM
ARG TORCH_VERSION=2.4.1

RUN apt-get update && apt-get install -y --no-install-recommends \
curl \
&& rm -rf /var/lib/apt-get/lists/*

COPY requirements.txt .

RUN python -m pip install --upgrade pip setuptools wheel && \
if [ "$TARGETPLATFORM" = "linux/arm64" ]; then \
python -m pip install --no-cache-dir torch==${TORCH_VERSION}; \
else \
python -m pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu --trusted-host download.pytorch.org torch==${TORCH_VERSION}; \
fi && \
grep -v '^torch' requirements.txt > requirements-no-torch.txt && \
python -m pip install --no-cache-dir -r requirements-no-torch.txt


RUN python -c "from transformers import pipeline; pipeline('sentiment-analysis', model='distilbert-base-uncased-finetuned-sst-2-english')"

RUN apt-get update && apt-get install -y curl && \
    curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl" && \
    chmod +x kubectl && mv kubectl /usr/local/bin/

COPY . .

EXPOSE 8000

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]