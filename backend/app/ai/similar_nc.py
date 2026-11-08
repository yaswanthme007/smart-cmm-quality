"""Similar past NCs (Section 19, COULD): TF-IDF + cosine similarity, computed locally.

Implemented with numpy (already a dependency) instead of scikit-learn to keep the image small;
it is the same textbook TF-IDF (smoothed idf, l2-normalised rows). No external API is called.
Suggestions only, labelled "Suggested from past NCs" in the UI.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Machine, Measurement, NcMeasurement, NonConformance
from app.models.enums import NcStatus

_TOKEN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(text.lower())


def tfidf(docs: list[list[str]]) -> np.ndarray:
    vocab = {t: i for i, t in enumerate(sorted({t for d in docs for t in d}))}
    n = len(docs)
    df = Counter(t for d in docs for t in set(d))
    idf = np.array([math.log((1 + n) / (1 + df[t])) + 1 for t in vocab])
    matrix = np.zeros((n, len(vocab)))
    for row, doc in enumerate(docs):
        for t, c in Counter(doc).items():
            matrix[row, vocab[t]] = c
    matrix *= idf
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms[norms == 0] = 1
    return matrix / norms


@dataclass
class Similar:
    id: str
    nc_no: str
    score: float
    root_cause_category: str | None
    root_cause: str | None
    corrective_action: str | None


def nc_text(session: Session, nc: NonConformance, with_actions: bool) -> str:
    chars = session.execute(
        select(Measurement.char_no, Measurement.char_name)
        .join(NcMeasurement, NcMeasurement.measurement_id == Measurement.id)
        .where(NcMeasurement.nc_id == nc.id)
    ).all()
    machine = session.get(Machine, nc.machine_id) if nc.machine_id else None
    parts = [f"{c} {n or ''}" for c, n in chars] + [machine.code if machine else ""]
    if with_actions:
        parts += [nc.root_cause or "", nc.corrective_action or "", nc.containment or ""]
    return " ".join(parts)


def similar_ncs(session: Session, nc: NonConformance, top: int = 3) -> list[Similar]:
    closed = list(
        session.scalars(
            select(NonConformance).where(
                NonConformance.status == NcStatus.CLOSED, NonConformance.id != nc.id
            )
        )
    )
    if not closed:
        return []
    docs = [tokens(nc_text(session, nc, with_actions=True))] + [
        tokens(nc_text(session, c, with_actions=True)) for c in closed
    ]
    matrix = tfidf(docs)
    scores = matrix[1:] @ matrix[0]
    order = np.argsort(-scores)[:top]
    return [
        Similar(
            id=str(closed[i].id),
            nc_no=closed[i].nc_no,
            score=round(float(scores[i]), 3),
            root_cause_category=closed[i].root_cause_category.value
            if closed[i].root_cause_category
            else None,
            root_cause=closed[i].root_cause,
            corrective_action=closed[i].corrective_action,
        )
        for i in order
        if scores[i] > 0.05
    ]
