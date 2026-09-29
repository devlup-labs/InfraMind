"""Loading, saving and publishing the Chronos model."""
import logging
from pathlib import Path

import torch
from chronos import ChronosPipeline

from . import config

logger = logging.getLogger(__name__)


def load_pipeline(name_or_path: str) -> ChronosPipeline:
    """Load Chronos in float32 on CPU (bfloat16 is fine for inference, not for training)."""
    return ChronosPipeline.from_pretrained(
        name_or_path,
        device_map="cpu",
        torch_dtype=torch.float32,
    )


def save_pipeline(pipeline: ChronosPipeline, out_dir: Path) -> Path:
    """Save the fine-tuned weights. The saved config keeps `chronos_config`, so
    ChronosPipeline.from_pretrained(out_dir) works exactly like the original."""
    out_dir.mkdir(parents=True, exist_ok=True)
    pipeline.model.model.save_pretrained(out_dir)
    logger.info("Model saved to %s", out_dir)
    return out_dir


def push_to_hub(model_dir: Path) -> bool:
    """Upload to Hugging Face if HF_TOKEN and HF_REPO_ID are set. Returns True if pushed."""
    if not (config.HF_TOKEN and config.HF_REPO_ID):
        logger.info("HF_TOKEN / HF_REPO_ID not set, skipping push to Hugging Face.")
        return False

    from huggingface_hub import HfApi

    api = HfApi(token=config.HF_TOKEN)
    api.create_repo(config.HF_REPO_ID, exist_ok=True, private=True)
    api.upload_folder(folder_path=str(model_dir), repo_id=config.HF_REPO_ID)
    logger.info("Model pushed to %s", config.HF_REPO_ID)
    return True