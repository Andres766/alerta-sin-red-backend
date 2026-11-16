import csv
import io

from app.application.services.reports import _safe
from app.infrastructure.seed import SEED_ZONES

API = "/api/v1"


def auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_exporta_las_evaluaciones_en_csv(client, admin_token):
    client.post(f"{API}/admin/evaluations", headers=auth(admin_token))
    res = client.get(f"{API}/admin/assessments.csv?days=7", headers=auth(admin_token))
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/csv")
    assert "attachment" in res.headers["content-disposition"]
    text = res.content.decode("utf-8-sig")  # incluye BOM para Excel
    rows = list(csv.DictReader(io.StringIO(text)))
    assert len(rows) == len(SEED_ZONES)
    assert {"zona", "nivel", "probabilidad", "rain_72h_mm", "modelo"} <= set(rows[0])
    assert any(r["departamento"] == "Nariño" for r in rows)


def test_neutraliza_formulas_de_excel():
    assert _safe("=HYPERLINK(\"http://malo\")") == "'=HYPERLINK(\"http://malo\")"
    assert _safe("+57 300") == "'+57 300" and _safe("@SUM(A1)") == "'@SUM(A1)"
    assert _safe("Pasto - Laderas") == "Pasto - Laderas" and _safe(12.5) == 12.5


def test_requiere_sesion_y_valida_el_rango(client, admin_token):
    assert client.get(f"{API}/admin/assessments.csv").status_code == 401
    bad = client.get(f"{API}/admin/assessments.csv?days=999", headers=auth(admin_token))
    assert bad.status_code == 422
