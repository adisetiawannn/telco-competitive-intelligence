# scripts/fine_tune_sentiment.py
"""
Two-stage fine-tuning untuk sentiment analysis telco Indonesia.

Stage 1: Fine-tune dengan SmSA (10.859 rows)
         → model belajar sentiment Bahasa Indonesia secara umum
         → 3 epoch, lr=2e-5

Stage 2: Domain adaptation dengan artikel telco (23 rows)
         → model kalibrasi ke konteks telco
         → 1 epoch, lr=1e-5 (lebih kecil agar tidak catastrophic forgetting)
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

import sqlite3
import logging
import numpy as np
import torch
from torch import nn
from torch.utils.data import Dataset, DataLoader
from transformers import (
    AutoTokenizer,
    AutoModelForSequenceClassification,
    get_linear_schedule_with_warmup,
)
from sklearn.utils.class_weight import compute_class_weight
from sklearn.metrics import (
    classification_report,
    confusion_matrix,
    f1_score,
)
from datetime import datetime, timezone

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

TRAINING_DB   = "data/training_data.db"
MODEL_NAME    = "w11wo/indonesian-roberta-base-sentiment-classifier"
OUTPUT_DIR    = "models/sentiment_v2"

LABEL2ID = {"negative": 0, "neutral": 1, "positive": 2}
ID2LABEL = {0: "negative", 1: "neutral", 2: "positive"}

# Stage 1 — SmSA
STAGE1_EPOCHS    = 3
STAGE1_LR        = 2e-5
STAGE1_BATCH     = 16
STAGE1_MAX_LEN   = 128

# Stage 2 — Telco domain adaptation
STAGE2_EPOCHS    = 1
STAGE2_LR        = 1e-5    # lebih kecil — cegah catastrophic forgetting
STAGE2_BATCH     = 8       # batch kecil karena data kecil
STAGE2_MAX_LEN   = 256     # artikel lebih panjang dari review

WARMUP_STEPS     = 100
F1_THRESHOLD     = 0.70    # minimum F1 untuk proceed ke stage 2


# ============================================================
# DATASET CLASS
# ============================================================

class SentimentDataset(Dataset):
    """PyTorch Dataset untuk sentiment classification."""

    def __init__(
        self,
        texts: list[str],
        labels: list[int],
        tokenizer,
        max_length: int = 128
    ):
        self.encodings = tokenizer(
            texts,
            truncation=True,
            padding=True,
            max_length=max_length,
            return_tensors="pt"
        )
        self.labels = torch.tensor(labels, dtype=torch.long)

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int) -> dict:
        return {
            "input_ids":      self.encodings["input_ids"][idx],
            "attention_mask": self.encodings["attention_mask"][idx],
            "labels":         self.labels[idx],
        }


# ============================================================
# DATA LOADERS
# ============================================================

def load_smsa_data(conn: sqlite3.Connection) -> tuple:
    """Load SmSA dataset dari database."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT text, sentiment_label FROM smsa_dataset
        WHERE split = 'train'
    """)
    train_rows = cursor.fetchall()

    cursor.execute("""
        SELECT text, sentiment_label FROM smsa_dataset
        WHERE split = 'valid'
    """)
    valid_rows = cursor.fetchall()

    train_texts  = [r[0] for r in train_rows]
    train_labels = [LABEL2ID[r[1]] for r in train_rows]
    valid_texts  = [r[0] for r in valid_rows]
    valid_labels = [LABEL2ID[r[1]] for r in valid_rows]

    logger.info(
        f"SmSA loaded — train: {len(train_texts)}, "
        f"valid: {len(valid_texts)}"
    )
    return train_texts, train_labels, valid_texts, valid_labels


def load_telco_data(conn: sqlite3.Connection) -> tuple:
    """Load labeled telco articles dari database."""
    cursor = conn.cursor()

    cursor.execute("""
        SELECT judul || ' ' || COALESCE(summary, ''), sentiment_label
        FROM training_articles
        WHERE sentiment_label IS NOT NULL
          AND sentiment_label != 'skip'
    """)
    rows = cursor.fetchall()

    texts  = [r[0] for r in rows]
    labels = [LABEL2ID[r[1]] for r in rows]

    logger.info(f"Telco data loaded — {len(texts)} articles")
    return texts, labels


# ============================================================
# CLASS WEIGHTS
# ============================================================

def compute_weights(labels: list[int]) -> torch.Tensor:
    """
    Hitung class weights untuk handle imbalance.
    Class yang jarang → weight lebih tinggi.
    """
    unique_classes = sorted(set(labels))
    weights = compute_class_weight(
        class_weight="balanced",
        classes=np.array(unique_classes),
        y=np.array(labels)
    )

    # Pastikan semua 3 class ada
    full_weights = np.ones(3)
    for i, cls in enumerate(unique_classes):
        full_weights[cls] = weights[i]

    logger.info(f"Class weights: {dict(zip(ID2LABEL.values(), full_weights))}")
    return torch.tensor(full_weights, dtype=torch.float)


# ============================================================
# TRAINING LOOP
# ============================================================

def train_epoch(
    model,
    dataloader: DataLoader,
    optimizer,
    scheduler,
    criterion,
    device: str
) -> float:
    """Satu epoch training — return average loss."""
    model.train()
    total_loss = 0

    for batch in dataloader:
        optimizer.zero_grad()

        input_ids      = batch["input_ids"].to(device)
        attention_mask = batch["attention_mask"].to(device)
        labels         = batch["labels"].to(device)

        outputs = model(
            input_ids=input_ids,
            attention_mask=attention_mask
        )

        # Pakai custom criterion dengan class weights
        loss = criterion(outputs.logits, labels)
        loss.backward()

        # Gradient clipping — cegah exploding gradients
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)

        optimizer.step()
        scheduler.step()

        total_loss += loss.item()

    return total_loss / len(dataloader)


def evaluate(
    model,
    dataloader: DataLoader,
    device: str
) -> tuple:
    """Evaluasi model — return F1 score dan classification report."""
    model.eval()
    all_preds  = []
    all_labels = []

    with torch.no_grad():
        for batch in dataloader:
            input_ids      = batch["input_ids"].to(device)
            attention_mask = batch["attention_mask"].to(device)
            labels         = batch["labels"]

            outputs = model(
                input_ids=input_ids,
                attention_mask=attention_mask
            )

            preds = torch.argmax(outputs.logits, dim=1).cpu()
            all_preds.extend(preds.numpy())
            all_labels.extend(labels.numpy())

    f1     = f1_score(all_labels, all_preds, average="macro")
    report = classification_report(
        all_labels, all_preds,
        target_names=["negative", "neutral", "positive"],
        output_dict=True
    )

    return f1, report


# ============================================================
# FINE-TUNING STAGES
# ============================================================

def stage1_smsa(
    model,
    tokenizer,
    train_texts, train_labels,
    valid_texts, valid_labels,
    device: str
) -> float:
    """
    Stage 1 — Fine-tune dengan SmSA.
    Return best validation F1.
    """
    logger.info("=" * 50)
    logger.info("STAGE 1 — SmSA fine-tuning")
    logger.info("=" * 50)

    train_dataset = SentimentDataset(
        train_texts, train_labels, tokenizer, STAGE1_MAX_LEN
    )
    valid_dataset = SentimentDataset(
        valid_texts, valid_labels, tokenizer, STAGE1_MAX_LEN
    )

    train_loader = DataLoader(
        train_dataset, batch_size=STAGE1_BATCH, shuffle=True
    )
    valid_loader = DataLoader(
        valid_dataset, batch_size=STAGE1_BATCH * 2
    )

    # Class weights untuk handle imbalance SmSA
    weights   = compute_weights(train_labels).to(device)
    criterion = nn.CrossEntropyLoss(weight=weights)

    optimizer = torch.optim.AdamW(
        model.parameters(), lr=STAGE1_LR, weight_decay=0.01
    )

    total_steps = len(train_loader) * STAGE1_EPOCHS
    scheduler   = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=WARMUP_STEPS,
        num_training_steps=total_steps
    )

    best_f1        = 0.0
    best_model_dir = f"{OUTPUT_DIR}/stage1_best"

    for epoch in range(1, STAGE1_EPOCHS + 1):
        train_loss = train_epoch(
            model, train_loader, optimizer,
            scheduler, criterion, device
        )
        val_f1, report = evaluate(model, valid_loader, device)

        logger.info(
            f"Epoch {epoch}/{STAGE1_EPOCHS} — "
            f"loss: {train_loss:.4f}, val_F1: {val_f1:.4f}"
        )
        logger.info(
            f"  neg: {report['negative']['f1-score']:.3f} | "
            f"neu: {report['neutral']['f1-score']:.3f} | "
            f"pos: {report['positive']['f1-score']:.3f}"
        )

        if val_f1 > best_f1:
            best_f1 = val_f1
            Path(best_model_dir).mkdir(parents=True, exist_ok=True)
            model.save_pretrained(best_model_dir)
            tokenizer.save_pretrained(best_model_dir)
            logger.info(f"  ✓ Best model saved (F1={best_f1:.4f})")

    logger.info(f"Stage 1 complete. Best F1: {best_f1:.4f}")
    return best_f1


def stage2_telco(
    model,
    tokenizer,
    telco_texts: list[str],
    telco_labels: list[int],
    device: str
) -> float:
    """
    Stage 2 — Domain adaptation dengan artikel telco.
    Lebih sedikit epoch dan learning rate lebih kecil.
    """
    logger.info("=" * 50)
    logger.info("STAGE 2 — Telco domain adaptation")
    logger.info("=" * 50)

    dataset = SentimentDataset(
        telco_texts, telco_labels, tokenizer, STAGE2_MAX_LEN
    )
    loader  = DataLoader(
        dataset, batch_size=STAGE2_BATCH, shuffle=True
    )

    # Class weights untuk telco data
    weights   = compute_weights(telco_labels).to(device)
    criterion = nn.CrossEntropyLoss(weight=weights)

    # LR lebih kecil — cegah catastrophic forgetting
    optimizer = torch.optim.AdamW(
        model.parameters(), lr=STAGE2_LR, weight_decay=0.01
    )

    total_steps = len(loader) * STAGE2_EPOCHS
    scheduler   = get_linear_schedule_with_warmup(
        optimizer,
        num_warmup_steps=min(10, total_steps // 4),
        num_training_steps=total_steps
    )

    for epoch in range(1, STAGE2_EPOCHS + 1):
        train_loss = train_epoch(
            model, loader, optimizer,
            scheduler, criterion, device
        )
        logger.info(
            f"Epoch {epoch}/{STAGE2_EPOCHS} — "
            f"loss: {train_loss:.4f}"
        )

    # Simpan final model
    final_dir = f"{OUTPUT_DIR}/final"
    Path(final_dir).mkdir(parents=True, exist_ok=True)
    model.save_pretrained(final_dir)
    tokenizer.save_pretrained(final_dir)
    logger.info(f"Stage 2 complete. Model saved to {final_dir}")

    return train_loss


# ============================================================
# MAIN
# ============================================================

def run_fine_tuning() -> None:
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    logger.info(f"Device: {device}")

    # Load model dan tokenizer
    logger.info(f"Loading model: {MODEL_NAME}")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)
    model     = AutoModelForSequenceClassification.from_pretrained(
        MODEL_NAME,
        num_labels=3,
        id2label=ID2LABEL,
        label2id=LABEL2ID,
        ignore_mismatched_sizes=True
    )
    model.to(device)

    # Load data
    conn = sqlite3.connect(TRAINING_DB)
    train_texts, train_labels, valid_texts, valid_labels = load_smsa_data(conn)
    telco_texts, telco_labels = load_telco_data(conn)
    conn.close()

    # Stage 1
    best_f1 = stage1_smsa(
        model, tokenizer,
        train_texts, train_labels,
        valid_texts, valid_labels,
        device
    )

    # Gate — cek apakah Stage 1 cukup baik
    if best_f1 < F1_THRESHOLD:
        logger.warning(
            f"Stage 1 F1 ({best_f1:.4f}) di bawah threshold "
            f"({F1_THRESHOLD}). Review data dan hyperparameter."
        )
        logger.warning("Melanjutkan ke Stage 2 anyway untuk baseline...")
    else:
        logger.info(f"Stage 1 passed threshold. Lanjut ke Stage 2.")

    # Load best Stage 1 model untuk Stage 2
    logger.info("Loading best Stage 1 model untuk Stage 2...")
    model = AutoModelForSequenceClassification.from_pretrained(
        f"{OUTPUT_DIR}/stage1_best"
    )
    model.to(device)

    # Stage 2
    stage2_telco(model, tokenizer, telco_texts, telco_labels, device)

    logger.info("\n=== FINE-TUNING COMPLETE ===")
    logger.info(f"Model saved to: {OUTPUT_DIR}/final")
    logger.info("Update MODEL_NAME di nlp_processor.py ke path ini")
    logger.info("lalu jalankan: python -m src.ingestion.nlp_processor")


if __name__ == "__main__":
    run_fine_tuning()