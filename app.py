import logging
import os
import time
import asyncio

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import pipeline
from prometheus_fastapi_instrumentator import Instrumentator
from pythonjsonlogger import jsonlogger

logger = logging.getLogger("inframind-model")
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter("%(asctime)s %(levelname)s %(name)s %(message)s")
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

# 1. Pull dynamic configurations
inference_timeout = float(os.getenv("INFERENCE_TIMEOUT", "2.0"))
max_batch_size = int(os.getenv("MAX_BATCH_SIZE", "32"))
max_concurrent_workers = int(os.getenv("MAX_CONCURRENT_WORKERS", "4"))

# 2. Create a semaphore to strictly limit concurrent model executions
concurrency_semaphore = asyncio.Semaphore(max_concurrent_workers)

logger.info("Loading DistilBERT model into memory...")
try:
    # 3. Wire the batch size directly into the HuggingFace pipeline
    classifier = pipeline(
        "sentiment-analysis",
        model="distilbert-base-uncased-finetuned-sst-2-english",
        batch_size=max_batch_size
    )
    logger.info("DistilBERT model loaded successfully.")
except Exception as e:
    logger.error("Failed to load model", extra={"error": str(e)})
    raise RuntimeError("Model initialization failed")

app = FastAPI(title="InfraMind Mock ML API")
Instrumentator().instrument(app).expose(app)

class InferenceRequest(BaseModel):
    text: str

class SentimentResponse(BaseModel):
    label: str
    score: float

@app.post("/predict", response_model=SentimentResponse)
async def predict(request: InferenceRequest):
    logger.info(
        "Received inference request",
        extra={"text_length": len(request.text)}
    )

    start = time.time()

    try:
        # 4. Force requests to wait in line if workers are maxed out
        async with concurrency_semaphore:
            # When inside the semaphore block, execute the model
            result = classifier(request.text)[0]
            
        elapsed = time.time() - start

        if elapsed > inference_timeout:
            logger.warning(
                "Inference request exceeded configured timeout",
                extra={
                    "elapsed_seconds": round(elapsed, 2),
                    "configured_timeout_seconds": inference_timeout,
                }
            )

        logger.info(
            "Prediction successful",
            extra={
                "predicted_label": result["label"],
                "elapsed_seconds": round(elapsed, 2),
                "configured_timeout_seconds": inference_timeout,
            }
        )

        return SentimentResponse(
            label=result["label"],
            score=result["score"]
        )

    except Exception as e:
        logger.error(
            "Error during prediction",
            extra={"error": str(e)}
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error during inference"
        )

@app.get("/health")
def health_check():
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)