"""Capture real API responses from a running, freshly seeded backend as frontend test fixtures.

    (backend running on :8000 after `python -m app.seed --reset`)
    python scripts/capture-fixtures.py

Fixtures contain only the synthetic demo dataset.
"""

import json
from pathlib import Path

import httpx

OUT = Path(__file__).resolve().parent.parent / "src" / "__tests__" / "fixtures"
OUT.mkdir(parents=True, exist_ok=True)

c = httpx.Client(base_url="http://127.0.0.1:8000/api", timeout=30)
c.post("/auth/login", json={"email": "reviewer@northwind.example", "password": "demo-password-2026"}).raise_for_status()


def save(name: str, path: str) -> dict:
    data = c.get(path).json()
    (OUT / f"{name}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    return data


save("me", "/auth/me")
save("meta", "/meta")
save("dashboard", "/dashboard")
items = save("candidates", "/candidates")["items"]
by_name = {i["full_name"]: i["id"] for i in items}
maya = save("candidate-maya", f"/candidates/{by_name['Maya Thompson']}")
save("candidate-tom", f"/candidates/{by_name['Tom Becker']}")
jordan = save("candidate-jordan", f"/candidates/{by_name['Jordan Ellis']}")
save("document-injection", f"/documents/{jordan['documents'][0]['id']}")
save("document-license", f"/documents/{next(d['id'] for d in maya['documents'] if d['original_filename'].startswith('rn_license'))}")
save("job-matches", f"/job-roles/{maya['job']['id']}/matches")
print("fixtures written to", OUT)
