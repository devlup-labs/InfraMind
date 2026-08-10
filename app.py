import logging
import time
import subprocess
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from transformers import pipeline
from prometheus_fastapi_instrumentator import Instrumentator
from pythonjsonlogger import jsonlogger

from agents.main import app as langgraph_app
from agents.monitoring_agent import fetch_comprehensive_metrics


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

app = FastAPI(title="InfraMind Mock ML API & Observability Backend")
Instrumentator().instrument(app).expose(app)

class InferenceRequest(BaseModel):
    text: str

class SentimentResponse(BaseModel):
    label: str
    score: float

@app.post("/predict", response_model=SentimentResponse)
async def predict(request: InferenceRequest):
    logger.info("Received inference request", extra={"text_length": len(request.text)})
    try:
        result = classifier(request.text)[0]
        logger.info("Prediction successful", extra={"predicted_label": result['label']})
        return SentimentResponse(label=result['label'], score=result['score'])
    except Exception as e:
        logger.error("Error during prediction", extra={"error": str(e)})
        raise HTTPException(status_code=500, detail="Internal server error during inference")

@app.get("/health")
def health_check():
    return {"status": "healthy"}


memory_store = {
    "pipeline_status": {
        "suspect_metric": "none",
        "anomaly_detected": False,
        "elapsed_seconds": 0,
        "agents": {
            "monitoring": {"status": "standby"},
            "root_cause": {"status": "standby"},
            "optimization": {"status": "standby"},
            "reporting": {"status": "standby"}
        }
    },
    "latest_incident": {
        "status": "No anomaly",
        "report": "No incident report yet. Run the pipeline to generate an analysis of the current system state.",
        "summary": ""
    },
    "past_incidents": [],
    "logs": [] 
}


@app.get("/api/metrics")
def get_metrics():
    """Returns the live metrics snapshot for the UI."""
    snapshot = fetch_comprehensive_metrics()
    return snapshot.get("metrics", {})

@app.get("/api/pipelineStatus")
def get_pipeline_status():
    """Returns the current state of the LangGraph agents."""
    return memory_store["pipeline_status"]

@app.get("/api/incidentLatest")
def get_latest_incident():
    """Returns the most recent incident report."""
    return memory_store["latest_incident"]

@app.get("/api/incidents")
def get_past_incidents():
    """Returns the history of mitigated incidents."""
    return memory_store["past_incidents"]

@app.get("/api/logs")
def get_logs():
    """Returns system logs for the live log stream."""
    return memory_store["logs"]


def execute_agentic_pipeline():
    """Runs the LangGraph workflow without blocking the HTTP response."""
    global memory_store
    
    memory_store["pipeline_status"]["agents"]["monitoring"]["status"] = "running"
    memory_store["pipeline_status"]["agents"]["root_cause"]["status"] = "standby"
    memory_store["pipeline_status"]["agents"]["optimization"]["status"] = "standby"
    memory_store["pipeline_status"]["agents"]["reporting"]["status"] = "standby"
    
    start_time = time.time()
    
    try:
        result = langgraph_app.invoke({})
        
        # Safely check multiple possible keys where LangGraph might store the output
        analysis = (
            result.get("analysis") or 
            result.get("monitoring") or 
            result.get("monitoring_result") or 
            result.get("agent_output") or 
            {}
        )
        
        # If the result itself contains anomaly keys directly
        is_anomaly = analysis.get("anomaly_detected") or result.get("anomaly_detected", False)
        suspect_metric = analysis.get("suspect_metric") or result.get("suspect_metric", "none")
        
        memory_store["pipeline_status"]["anomaly_detected"] = is_anomaly
        memory_store["pipeline_status"]["suspect_metric"] = suspect_metric
        
        memory_store["latest_incident"] = {
            "status": result.get("final_status", "resolved" if is_anomaly else "No anomaly"),
            "report": result.get("incident_report", analysis.get("reasoning", "No report generated.")),
            "summary": result.get("root_cause", suspect_metric if is_anomaly else "System functioning normally.")
        }
        
        if is_anomaly:
            memory_store["past_incidents"].append({
                "anomaly": suspect_metric,
                "pod": result.get("affected_pod", "unknown"),
                "triggered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "root_cause": result.get("root_cause", "Unknown"),
                "duration_seconds": round(time.time() - start_time),
                "status": "resolved" if result.get("final_status") == "healthy" else "failed"
            })

    except Exception as e:
        logger.error(f"Pipeline execution failed: {str(e)}")
        memory_store["latest_incident"]["report"] = f"Pipeline failed: {str(e)}"
        memory_store["pipeline_status"]["anomaly_detected"] = False
        memory_store["pipeline_status"]["suspect_metric"] = "none"
    
    finally:
        memory_store["pipeline_status"]["elapsed_seconds"] = round(time.time() - start_time)
        for agent in memory_store["pipeline_status"]["agents"]:
            memory_store["pipeline_status"]["agents"][agent]["status"] = "completed"

@app.post("/api/pipelineRun")
def trigger_pipeline(background_tasks: BackgroundTasks):
    """Triggers the LangGraph agents to run in the background."""
    background_tasks.add_task(execute_agentic_pipeline)
    return {"message": "Pipeline initiated"}


class TrafficRequest(BaseModel):
    mode: str

@app.post("/api/trafficInject")
def inject_traffic(request: TrafficRequest):
    """Triggers traffic generation scripts to simulate load or anomalies."""
    try:
        subprocess.Popen(["python", "Traffic_injector.py", "--mode", request.mode])
        return {"status": "success", "message": f"Started {request.mode} traffic injection"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)