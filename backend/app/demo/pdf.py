"""Minimal PDF writer for synthetic demo/test documents (no third-party dependency).

`make_pdf(lines)` creates a one-page PDF with a real text layer; `make_pdf(None)` creates a
page containing only vector graphics — the shape of a scanned image with no text layer.
"""

from __future__ import annotations


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def make_pdf(lines: list[str] | None) -> bytes:
    if lines is None:
        content = "0.85 g 72 500 450 220 re f 0.6 g 90 520 200 12 re f 90 545 300 12 re f"
    else:
        parts = ["BT", "/F1 11 Tf", "14 TL", "72 760 Td"]
        for line in lines:
            safe = line.encode("cp1252", "replace").decode("cp1252")
            parts.append(f"({_escape(safe)}) Tj T*")
        parts.append("ET")
        content = "\n".join(parts)
    stream = content.encode("cp1252")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>",
    ]
    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    for off in offsets:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
