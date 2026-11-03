API = "/api/v1"


def test_ficha_del_modelo_es_publica_y_completa(client):
    res = client.get(f"{API}/model")
    assert res.status_code == 200
    card = res.json()
    assert card["version"].startswith("rf-") and card["algorithm"] == "RandomForestClassifier"
    assert card["n_samples"] > 0 and card["data_source"]
    assert set(card["feature_importances"]) == set(card["feature_order"])
    assert abs(sum(card["feature_importances"].values()) - 1) < 0.01
    assert 0 < card["metrics"]["test_f1_macro"] <= 1
    assert len(card["confusion_matrix"]) == 4 and card["labels"][0] == "BAJO"
    assert any("sintéticos" in item for item in card["limitations"])


def test_ficha_no_expone_la_huella_ni_rutas_internas(client):
    text = client.get(f"{API}/model").text
    assert "sha256" not in text and "joblib" not in text
