"""Upload validation, text extraction, PII redaction, prompt-injection screening and
evidence location. Everything here is deterministic and provider-independent."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass

from app.extraction.errors import ExtractionError

ALLOWED_EXTENSIONS = {".pdf": "application/pdf", ".txt": "text/plain", ".md": "text/markdown"}
MAX_TEXT_CHARS = 60_000
MIN_TEXT_CHARS = 20


# --------------------------------------------------------------------------- upload validation


def sanitize_filename(name: str) -> str:
    """Display-only filename: strip any path components and unsafe characters."""
    base = re.split(r"[\\/]", name or "")[-1]
    base = re.sub(r"[^A-Za-z0-9._ -]", "_", base).strip(" .")
    return (base or "document")[:200]


def validate_upload(filename: str, data: bytes, max_bytes: int) -> tuple[str, str]:
    """Return (extension, content_type) or raise ExtractionError. Upload-time, cheap checks only."""
    ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ExtractionError(
            "unsupported_type",
            f"Unsupported file type '{ext or 'none'}'. Upload a PDF with a text layer or a .txt/.md file.",
        )
    if not data:
        raise ExtractionError("empty_file", "The uploaded file is empty.")
    if len(data) > max_bytes:
        raise ExtractionError("file_too_large", f"File exceeds the {max_bytes // (1024 * 1024)} MB limit.")
    if ext == ".pdf" and not data.startswith(b"%PDF-"):
        raise ExtractionError("content_mismatch", "The file has a .pdf extension but is not a PDF.")
    if ext in (".txt", ".md"):
        if b"\x00" in data:
            raise ExtractionError("content_mismatch", "Text files must not contain binary data.")
        try:
            data.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise ExtractionError("bad_encoding", "Text files must be UTF-8 encoded.") from exc
    return ext, ALLOWED_EXTENSIONS[ext]


# --------------------------------------------------------------------------- text extraction


@dataclass
class ExtractedText:
    text: str
    page_count: int | None


def extract_text(data: bytes, content_type: str) -> ExtractedText:
    if content_type == "application/pdf":
        from pypdf import PdfReader
        from pypdf.errors import PdfReadError

        try:
            reader = PdfReader(io.BytesIO(data))
            if reader.is_encrypted:
                raise ExtractionError("encrypted_pdf", "The PDF is password-protected. Upload an unprotected copy.")
            pages = [(page.extract_text() or "") for page in reader.pages]
        except ExtractionError:
            raise
        except (PdfReadError, ValueError, KeyError, TypeError) as exc:
            raise ExtractionError("unreadable_pdf", "The PDF could not be parsed. It may be corrupted.") from exc
        text = "\n\n".join(p.strip() for p in pages)
        page_count: int | None = len(pages)
    else:
        text = data.decode("utf-8-sig")
        page_count = None

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    if len(re.sub(r"\s", "", text)) < MIN_TEXT_CHARS:
        raise ExtractionError(
            "no_text_layer",
            "No readable text was found. The document may be a scanned image; OCR is not supported in this release. "
            "Upload a text-based PDF or enter the details manually.",
        )
    if len(text) > MAX_TEXT_CHARS:
        raise ExtractionError(
            "document_too_long",
            f"The document has {len(text):,} characters; the limit is {MAX_TEXT_CHARS:,}. Split it into smaller documents.",
        )
    return ExtractedText(text=text, page_count=page_count)


# --------------------------------------------------------------------------- PII minimization

_REDACTIONS = [
    ("[EMAIL]", re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("[SSN]", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("[PHONE]", re.compile(r"(?:\+?1[\s.-]?)?(?:\(\d{3}\)\s?|\b\d{3}[\s.-])\d{3}[\s.-]\d{4}\b")),
    (
        "[ADDRESS]",
        re.compile(r"\b\d{1,6}\s+(?:[A-Z][a-z]+\s){1,4}(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|Court|Ct|Way)\b\.?"),
    ),
]


def redact_pii(text: str) -> tuple[str, dict[str, int]]:
    """Replace contact details/SSNs with placeholders before text leaves the system."""
    counts: dict[str, int] = {}
    for placeholder, pattern in _REDACTIONS:
        text, n = pattern.subn(placeholder, text)
        if n:
            counts[placeholder.strip("[]").lower()] = n
    return text, counts


# --------------------------------------------------------------------------- prompt-injection screening

_INJECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "ignore_instructions",
        re.compile(
            r"\b(ignore|disregard|forget)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any)\b[^.\n]{0,20}\b(instructions?|prompts?|rules?|directions?)",
            re.I,
        ),
    ),
    ("role_override", re.compile(r"\byou are (now )?(an? |the )?(ai|assistant|model|chatbot|system|language model)\b", re.I)),
    ("system_prompt_reference", re.compile(r"\b(system prompt|developer message|system message|hidden instructions?)\b", re.I)),
    (
        "status_manipulation",
        re.compile(r"\b(mark|set|flag|record|classify|treat|list)\b[^.\n]{0,60}\bas\s+(verified|approved|compliant|eligible|cleared|valid|qualified)\b", re.I),
    ),
    ("new_instructions", re.compile(r"\b(new|updated|override|additional) instructions?\b", re.I)),
    ("chat_markup", re.compile(r"(</?\s*(system|instructions?|assistant|user|document)\s*>|^\s*(assistant|system)\s*:)", re.I | re.M)),
    (
        "scoring_manipulation",
        re.compile(
            r"\b(give|assign)\b[^.\n]{0,40}\b(this|the) (candidate|applicant)\b|\b(highest|maximum|perfect)\s+(possible\s+)?(match|score|rating)\b", re.I
        ),
    ),
]


def detect_injection(text: str) -> list[str]:
    """Names of instruction-like patterns found in untrusted document text."""
    return [name for name, pattern in _INJECTION_PATTERNS if pattern.search(text)]


# --------------------------------------------------------------------------- evidence location

_CHAR_MAP = str.maketrans({"–": "-", "—": "-", "−": "-", "‘": "'", "’": "'", "“": '"', "”": '"', " ": " ", "•": "-"})


def _normalize_with_map(text: str) -> tuple[str, list[int]]:
    """Lowercase, unify dashes/quotes, collapse whitespace; keep a map to original offsets."""
    out: list[str] = []
    index: list[int] = []
    prev_space = True
    for i, ch in enumerate(text.translate(_CHAR_MAP)):
        if ch.isspace():
            if not prev_space:
                out.append(" ")
                index.append(i)
            prev_space = True
            continue
        out.append(ch.lower())
        index.append(i)
        prev_space = False
    return "".join(out), index


class EvidenceLocator:
    """Finds verbatim (normalized) quotes in a document and maps them to original offsets."""

    def __init__(self, text: str) -> None:
        self.text = text
        self._norm, self._index = _normalize_with_map(text)

    @staticmethod
    def normalize(value: str) -> str:
        return _normalize_with_map(value)[0].strip()

    def locate(self, quote: str | None) -> tuple[int, int] | None:
        if not quote:
            return None
        needle = self.normalize(quote)
        if len(needle) < 3:
            return None
        pos = self._norm.find(needle)
        if pos < 0:
            return None
        start = self._index[pos]
        end = self._index[pos + len(needle) - 1] + 1
        return start, end

    def contains(self, value: str | None) -> bool:
        if not value:
            return False
        needle = self.normalize(value)
        return bool(needle) and needle in self._norm

    def contains_compact(self, value: str | None) -> bool:
        """Alphanumeric-only containment, for identifiers printed with varying separators."""
        if not value:
            return False
        squash = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
        needle = squash(value)
        return len(needle) >= 3 and needle in squash(self.text)
