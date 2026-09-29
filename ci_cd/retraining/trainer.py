"""Fine-tune the Chronos (T5) model on windowed metric data."""
import logging

import torch
from chronos import ChronosPipeline
from torch.utils.data import DataLoader, Dataset
from transformers import get_linear_schedule_with_warmup

from . import config
from .dataset_builder import Windows

logger = logging.getLogger(__name__)


class WindowDataset(Dataset):
    def __init__(self, windows: Windows):
        self.context = torch.from_numpy(windows.context)
        self.target = torch.from_numpy(windows.target)

    def __len__(self) -> int:
        return len(self.context)

    def __getitem__(self, i):
        return self.context[i], self.target[i]


def _tokenize(tokenizer, context: torch.Tensor, target: torch.Tensor):
    """Chronos tokenisation: mean-scale + quantise context, reuse the same scale for labels."""
    input_ids, attention_mask, scale = tokenizer.context_input_transform(context)
    labels, labels_mask = tokenizer.label_input_transform(target, scale)
    labels = labels.masked_fill(labels_mask == 0, -100)   # ignore padding in the loss
    return input_ids, attention_mask, labels


def fine_tune(pipeline: ChronosPipeline, train: Windows) -> list[float]:
    """Full fine-tune in place. Returns the mean loss per epoch."""
    torch.manual_seed(config.SEED)

    model = pipeline.model.model          # underlying HF T5ForConditionalGeneration
    tokenizer = pipeline.tokenizer

    loader = DataLoader(WindowDataset(train), batch_size=config.BATCH_SIZE, shuffle=True)
    total_steps = len(loader) * config.EPOCHS

    optimizer = torch.optim.AdamW(
        model.parameters(), lr=config.LEARNING_RATE, weight_decay=config.WEIGHT_DECAY
    )
    scheduler = get_linear_schedule_with_warmup(
        optimizer, int(total_steps * config.WARMUP_RATIO), total_steps
    )

    model.train()
    epoch_losses: list[float] = []
    for epoch in range(config.EPOCHS):
        running, batches = 0.0, 0
        for context, target in loader:
            input_ids, attention_mask, labels = _tokenize(tokenizer, context, target)
            loss = model(
                input_ids=input_ids, attention_mask=attention_mask, labels=labels
            ).loss

            optimizer.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), config.GRAD_CLIP)
            optimizer.step()
            scheduler.step()

            running += loss.item()
            batches += 1

        epoch_losses.append(running / max(batches, 1))
        logger.info("Epoch %d/%d  loss=%.4f", epoch + 1, config.EPOCHS, epoch_losses[-1])

    model.eval()
    return epoch_losses