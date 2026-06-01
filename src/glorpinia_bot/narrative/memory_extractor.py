"""Extrai memórias úteis de uma interação antes da persistência RAG.

A ideia deste módulo é transformar conversa crua em uma frase curta e
reaproveitável. Isso reduz ruído, evita salvar turnos sem valor duradouro e
mantém a memória focada em fatos/preferências/sinais sociais do usuário.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional


MEMORY_TYPES = {
    "preference",
    "fact",
    "running_joke",
    "emotion_signal",
    "relationship",
    "ignore",
}
MIN_MEMORY_CONFIDENCE = 0.65
MAX_SUMMARY_CHARS = 180


@dataclass(frozen=True)
class MemoryExtraction:
    """Resultado normalizado da extração de memória."""

    memory_type: str
    summary: str
    confidence: float
    ttl_days: Optional[int] = None

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


_IGNORE_PREFIXES = (
    "!",
    "/",
    ".",
)

_IGNORE_PATTERNS = [
    re.compile(r"^\s*(oi|ol[áa]|opa|salve|bom dia|boa tarde|boa noite|valeu|obrigad[oa])\b", re.I),
    re.compile(r"^\s*(kkkk+|haha+|hehe+|rsrs+)\s*$", re.I),
    re.compile(r"\b(que horas|quanto custa|qual (é|eh)|como faz|me explica|por que|quando)\b", re.I),
]

_EXTRACTION_RULES: list[tuple[str, float, Optional[int], list[re.Pattern[str]]]] = [
    (
        "preference",
        0.86,
        None,
        [
            re.compile(r"\b(eu\s+)?(gosto|curto|adoro|amo|prefiro)\b.+", re.I),
            re.compile(r"\b(eu\s+)?(odeio|detesto|n[ãa]o gosto|n[ãa]o curto)\b.+", re.I),
            re.compile(r"\b(meu|minha)\s+.+\s+favorit[oa]\b.+", re.I),
        ],
    ),
    (
        "fact",
        0.82,
        None,
        [
            re.compile(r"\b(meu nome (é|eh)|me chamo|sou conhecid[oa] como)\b.+", re.I),
            re.compile(r"\b(eu\s+)?(moro|vivo|trabalho|estudo|fa[çc]o|tenho|sou)\b.+", re.I),
            re.compile(r"\b(minha|meu)\s+(idade|anivers[áa]rio|cidade|profiss[ãa]o|trabalho|curso)\b.+", re.I),
        ],
    ),
    (
        "emotion_signal",
        0.78,
        14,
        [
            re.compile(r"\b(estou|t[ôo]|me sinto|ando)\s+(triste|feliz|cansad[oa]|ansios[oa]|nervos[oa]|animad[oa]|mal|bem|estressad[oa])\b.*", re.I),
            re.compile(r"\b(hoje|agora)\s+(foi|t[áa]|est[áa])\s+.+\b(dif[íi]cil|pesad[oa]|bom|boa|incr[íi]vel|horr[íi]vel)\b", re.I),
        ],
    ),
    (
        "relationship",
        0.8,
        None,
        [
            re.compile(r"\b(é|eh|sou|somos)\s+(meu|minha|amig[oa]s?|namorad[oa]|irm[ãa]o|irm[ãa]|primo|prima|m[ãa]e|pai)\b.+", re.I),
            re.compile(r"\b(meu|minha)\s+(amig[oa]|namorad[oa]|irm[ãa]o|irm[ãa]|primo|prima|m[ãa]e|pai)\b.+", re.I),
        ],
    ),
    (
        "running_joke",
        0.74,
        60,
        [
            re.compile(r"\b(piada interna|meme do canal|nosso meme|running joke|sempre zoa|sempre brinca|lembra do meme)\b.+", re.I),
            re.compile(r"\b(glorpinia|chat)\s+sempre\s+(fala|chama|zoa|brinca)\b.+", re.I),
        ],
    ),
]


def _clean_text(text: object) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    cleaned = re.sub(r"\[\[COOKIE:[^\]]+\]\]", "", cleaned).strip()
    return cleaned


def _compact_summary(author: str, memory_type: str, query: str, response: str) -> str:
    nick = _clean_text(author) or "usuário"
    query = _clean_text(query)
    response = _clean_text(response)

    prefixes = {
        "preference": f"{nick} indicou uma preferência: ",
        "fact": f"{nick} compartilhou um fato pessoal: ",
        "running_joke": f"{nick} estabeleceu uma piada recorrente: ",
        "emotion_signal": f"{nick} sinalizou estado emocional: ",
        "relationship": f"{nick} descreveu uma relação: ",
    }
    summary = f"{prefixes.get(memory_type, f'{nick}: ')}{query}"

    if memory_type == "running_joke" and response:
        summary = f"{summary} | resposta da Glorpinia: {response}"

    if len(summary) > MAX_SUMMARY_CHARS:
        summary = summary[: MAX_SUMMARY_CHARS - 1].rstrip() + "…"

    return summary


def _should_ignore_query(query: str) -> bool:
    if not query:
        return True

    if query.startswith(_IGNORE_PREFIXES):
        return True

    if len(query) < 8:
        return True

    return any(pattern.search(query) for pattern in _IGNORE_PATTERNS)


def extract_user_memory(channel: str, author: str, query: str, response: str) -> dict[str, object]:
    """Classifica e resume uma interação em uma memória persistível.

    Retorna sempre um dicionário com `memory_type`, `summary`, `confidence` e
    `ttl_days`. O chamador deve persistir apenas quando `memory_type != "ignore"`
    e `confidence >= MIN_MEMORY_CONFIDENCE`.
    """
    clean_query = _clean_text(query)
    clean_response = _clean_text(response)

    if not _clean_text(channel) or not _clean_text(author) or _should_ignore_query(clean_query):
        return MemoryExtraction("ignore", "", 0.0).to_dict()

    for memory_type, confidence, ttl_days, patterns in _EXTRACTION_RULES:
        if any(pattern.search(clean_query) for pattern in patterns):
            summary = _compact_summary(author, memory_type, clean_query, clean_response)
            return MemoryExtraction(memory_type, summary, confidence, ttl_days).to_dict()

    return MemoryExtraction("ignore", "", 0.25).to_dict()


def is_persistable_memory(extraction: dict[str, object], min_confidence: float = MIN_MEMORY_CONFIDENCE) -> bool:
    """Indica se o resultado da extração deve ser salvo."""
    memory_type = extraction.get("memory_type")
    confidence = extraction.get("confidence", 0.0)
    summary = _clean_text(extraction.get("summary", ""))

    try:
        numeric_confidence = float(confidence)
    except (TypeError, ValueError):
        numeric_confidence = 0.0

    return memory_type in MEMORY_TYPES - {"ignore"} and bool(summary) and numeric_confidence >= min_confidence
