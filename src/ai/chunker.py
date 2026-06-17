"""
Chunker markdown-aware para los READMEs de los repositorios.

Estrategia:
  1. Limpieza: quita HTML, badges, links, imágenes — el ruido baja
     drásticamente la calidad de los embeddings.
  2. Split por encabezados de markdown (``#``, ``##``, ``###``): cada
     sección se trata como un chunk inicial.
  3. Si una sección excede ``MAX_CHARS`` (1500 ≈ 375 tokens), se divide
     por frases preservando solapamiento de ``OVERLAP_CHARS`` (200 chars)
     para no romper la continuidad semántica.
  4. Secciones cortas adyacentes se MERGEAN hasta llegar a ``MIN_CHARS``
     (300) para evitar chunks "huérfanos" sin contexto.

Salida: lista de dicts ``{chunk_index, text, char_count, section_path}``
listas para embeddings y persistencia.
"""
from __future__ import annotations

import hashlib
import re
from typing import List, Optional, Tuple


MAX_CHARS = 1500       # ~375 tokens; suficiente para que el contexto sea útil
MIN_CHARS = 300        # Por debajo, se mergea con el siguiente
OVERLAP_CHARS = 200    # Solapamiento entre chunks divididos por longitud


# Patrones de limpieza markdown
_RE_HTML = re.compile(r"<[^>]+>")
_RE_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_RE_LINK = re.compile(r"\[([^\]]+)\]\([^)]*\)")          # → mantiene texto
_RE_EMPTY_LINK = re.compile(r"\[\s*\]\([^)]*\)")         # [](url) artefactos
_RE_BADGE = re.compile(r"!\[[^\]]*\]\([^)]*shields\.io[^)]*\)")
_RE_FENCE = re.compile(r"```[\s\S]*?```")                 # bloques de código
_RE_INLINE_CODE = re.compile(r"`[^`\n]+`")
_RE_HEADER = re.compile(r"^(#{1,6})\s+(.+)$", re.MULTILINE)
_RE_MULTIPLE_WS = re.compile(r"\n\s*\n\s*\n+")
_RE_TRAILING_WS = re.compile(r"[ \t]+$", re.MULTILINE)


def clean_markdown(text: str) -> str:
    """Limpia markdown ruidoso conservando el contenido semántico."""
    if not text:
        return ""

    # Eliminar bloques de código (no aportan en una búsqueda semántica
    # de "qué hace este repo" y rompen los embeddings)
    text = _RE_FENCE.sub(" ", text)
    # Inline code → mantener el contenido sin las backticks
    text = _RE_INLINE_CODE.sub(lambda m: m.group(0)[1:-1], text)
    # Badges (shields.io) → fuera
    text = _RE_BADGE.sub("", text)
    # Imágenes → fuera
    text = _RE_IMG.sub("", text)
    # Links con texto vacío (artefactos típicos de README) → fuera
    text = _RE_EMPTY_LINK.sub("", text)
    # Links → mantener solo el texto visible
    text = _RE_LINK.sub(r"\1", text)
    # HTML residual
    text = _RE_HTML.sub(" ", text)
    # Trailing whitespace + saltos múltiples
    text = _RE_TRAILING_WS.sub("", text)
    text = _RE_MULTIPLE_WS.sub("\n\n", text)
    return text.strip()


def _split_by_headers(text: str) -> List[Tuple[str, str]]:
    """Divide el texto por encabezados markdown.

    Returns: lista de (section_path, body) con section_path como
    breadcrumb tipo ``Installation > Linux``.
    """
    matches = list(_RE_HEADER.finditer(text))
    if not matches:
        return [("", text)]

    sections: List[Tuple[str, str]] = []
    # Texto antes del primer header
    if matches[0].start() > 0:
        intro = text[:matches[0].start()].strip()
        if intro:
            sections.append(("", intro))

    # Stack de breadcrumb (nivel → título)
    crumb_stack: List[Tuple[int, str]] = []
    for i, m in enumerate(matches):
        level = len(m.group(1))
        title = m.group(2).strip()

        # Recortar el stack a nivel padre
        while crumb_stack and crumb_stack[-1][0] >= level:
            crumb_stack.pop()
        crumb_stack.append((level, title))
        path = " > ".join(t for _, t in crumb_stack)

        body_start = m.end()
        body_end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[body_start:body_end].strip()
        if body:
            sections.append((path, body))

    return sections


def _split_long_section(body: str, max_chars: int, overlap: int) -> List[str]:
    """Divide un cuerpo largo en chunks con solapamiento por frases."""
    if len(body) <= max_chars:
        return [body]

    # Romper por frases primero (separadores comunes: ., !, ?, \n\n)
    sentences = re.split(r"(?<=[\.\?!])\s+|\n\n", body)
    chunks: List[str] = []
    current: List[str] = []
    current_len = 0

    for s in sentences:
        s = s.strip()
        if not s:
            continue
        slen = len(s) + 1  # +1 por separador
        if current_len + slen > max_chars and current:
            chunks.append(" ".join(current).strip())
            # Iniciar siguiente chunk con solapamiento (últimas frases)
            overlap_text = " ".join(current)[-overlap:]
            current = [overlap_text, s] if overlap_text else [s]
            current_len = len(overlap_text) + slen
        else:
            current.append(s)
            current_len += slen

    if current:
        chunks.append(" ".join(current).strip())

    return chunks


def chunk_text(
    text: str,
    *,
    max_chars: int = MAX_CHARS,
    min_chars: int = MIN_CHARS,
    overlap: int = OVERLAP_CHARS,
    header: Optional[str] = None,
) -> List[dict]:
    """Pipeline completo: limpia, divide por headers, balancea tamaños.

    Args:
        text: contenido en markdown a chunkear.
        header: opcional, texto que se prepende a CADA chunk (p.ej. el
                nombre del repo) para que el embedding tenga contexto.

    Returns:
        Lista de dicts con ``chunk_index``, ``text``, ``char_count``,
        ``section_path`` (vacío si el README no tenía headers).
    """
    cleaned = clean_markdown(text)
    if not cleaned:
        return []

    sections = _split_by_headers(cleaned)

    # Mergear secciones cortas adyacentes
    merged: List[Tuple[str, str]] = []
    for path, body in sections:
        if merged and len(merged[-1][1]) < min_chars and len(body) < min_chars:
            prev_path, prev_body = merged[-1]
            joiner = "\n\n"
            merged[-1] = (prev_path or path, prev_body + joiner + body)
        else:
            merged.append((path, body))

    # Dividir secciones largas
    out: List[dict] = []
    idx = 0
    for path, body in merged:
        for piece in _split_long_section(body, max_chars, overlap):
            content = piece.strip()
            if not content:
                continue
            if header:
                final_text = f"{header}\n\n{content}"
            else:
                final_text = content
            out.append({
                "chunk_index": idx,
                "text": final_text,
                "char_count": len(final_text),
                "section_path": path,
            })
            idx += 1

    return out


def text_hash(text: str) -> str:
    """Hash determinista del contenido (para detectar cambios en re-index)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
