"""Fine-tune a Chronos pipeline on training windows (CPU, float32)."""
import logging
import math
import random
from typing import List

import numpy as np
import torch
from chronos import ChronosPipeline

from . import config
from .dataset_builder import Windows

logger = logging.getLogger(__name__)


def _seed_everything(seed: int) -> None:
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


def _batches(windows: Windows, batch_size: int, rng: np.random.Generator):
    order = rng.permutation(len(windows))
    for i in range(0, len(order), batch_size):
        sel = order[i:i + batch_size]
        yield torch.from_numpy(windows.context[sel]), torch.from_numpy(windows.target[sel])


def fine_tune(pipeline: ChronosPipeline, windows: Windows) -> List[float]:
    """Fine-tune the pipeline IN PLACE. Returns the mean training loss of each epoch.

    Targets must already have the model's native prediction_length
    (see model_io.prediction_length): Chronos asserts on it when tokenizing labels.
    """
    if len(windows) == 0:
        raise ValueError("No training windows to fine-tune on.")

    _seed_everything(config.SEED)
    rng = np.random.default_rng(config.SEED)

    tokenizer = pipeline.tokenizer
    model = pipeline.model.model                     # the underlying HF T5 model
    device = next(model.parameters()).device

    steps_per_epoch = math.ceil(len(windows) / config.BATCH_SIZE)
    total_steps = steps_per_epoch * config.EPOCHS
    warmup = max(1, int(total_steps * config.WARMUP_RATIO))

    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.LEARNING_RATE, weight_decay=config.WEIGHT_DECAY
    )

    def lr_lambda(step: int) -> float:               # linear warmup, then linear decay
        if step < warmup:
            return (step + 1) / warmup
        return max(0.0, (total_steps - step) / max(1, total_steps - warmup))

    scheduler = torch.optim.lr_scheduler.LambdaLR(optimizer, lr_lambda)

    model.train()
    epoch_losses: List[float] = []
    for epoch in range(config.EPOCHS):
        losses = []
        for context, target in _batches(windows, config.BATCH_SIZE, rng):
            input_ids, attention_mask, scale = tokenizer.context_input_transform(context)
            labels, labels_mask = tokenizer.label_input_transform(target, scale)
            labels = labels.masked_fill(~labels_mask.bool(), -100)   # ignore padding in the loss

            out = model(
                input_ids=input_ids.to(device),
                attention_mask=attention_mask.to(device),
                labels=labels.to(device),
            )

            optimizer.zero_grad(set_to_none=True)
            out.loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), config.GRAD_CLIP)
            optimizer.step()
            scheduler.step()
            losses.append(out.loss.item())

        epoch_losses.append(float(np.mean(losses)))
        logger.info("Epoch %d/%d loss=%.4f", epoch + 1, config.EPOCHS, epoch_losses[-1])

    model.eval()
    return epoch_losses
