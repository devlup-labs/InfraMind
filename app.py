import logging
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from transformers import pipeline
from prometheus_fastapi_instrumentator import Instrumentator
from pythonjsonlogger import jsonlogger

logger = logging.getLogger("inframind-model")
logHandler = logging.StreamHandler()
formatter = jsonlogger.JsonFormatter(
    "%(asctime)s %(levelname)s %(name)s %(message)s"
)
logHandler.setFormatter(formatter)
logger.addHandler(logHandler)
logger.setLevel(logging.INFO)

logger.info("Loading DistilBERT model into memory...")
try:
    classifier = pipeline(
        "sentiment-analysis",
        model="distilbert-base-uncased-finetuned-sst-2-english"
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
    # Log incoming request (logging length instead of full text to avoid log bloat)
    logger.info("Received inference request", extra={"text_length": len(request.text)})
    
    try:

        result = classifier(request.text)[0]
        
        logger.info("Prediction successful", extra={"predicted_label": result['label']})
        
        return SentimentResponse(
            label=result['label'],
            score=result['score']
        )
        
    except Exception as e:
        logger.error("Error during prediction", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Internal server error during inference")

@app.get("/health")
def health_check():
    return {"status": "healthy"}