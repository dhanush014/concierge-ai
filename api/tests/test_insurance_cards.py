"""Reading insurance cards: extract, confirm, network status, name check. Fake vision."""

import json
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.insurance.match import match_network, name_matches, norm
from tests.conftest import Factory, as_patient
from tests.fake_llm import FakeLLM

CARDS = Path(__file__).resolve().parents[2] / "data" / "cards"
TEST_PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n%%EOF\n"


def upload(client: TestClient, patient, name: str, data: bytes, kind: str = "insurance_card") -> str:
    resp = client.post("/me/documents", files={"file": (name, data, "application/octet-stream")},
                       data={"kind": kind}, headers=as_patient(patient))
    assert resp.status_code == 201, resp.text
    return resp.json()["id"]


def reading(**fields) -> str:
    base = {"payer": None, "plan_name": None, "member_name": None, "member_id": None, "group_number": None}
    return json.dumps(base | fields)


@pytest.fixture
def card(client: TestClient, make: Factory) -> dict:
    """A patient ("Test PatientN") with an uploaded card image."""
    patient = make.patient()
    return {"patient": patient, "doc": upload(client, patient, "card.png", (CARDS / "aja.png").read_bytes())}


def extract(client: TestClient, card: dict, patient=None):
    return client.post(f"/me/documents/{card['doc']}/extract", headers=as_patient(patient or card["patient"]))


# --- extract ---

def test_extract_saves_fields_as_extracted(client, db, card, fake_llm: FakeLLM) -> None:
    fake_llm.replies["vision"] = reading(payer="Riverbend Health", plan_name="Riverbend Silver HMO",
                                         member_name="Test Patient0", member_id="RBH1", group_number="123")
    resp = extract(client, card)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], body["network"], body["matched_payer"], body["name_warning"]) == (
        "extracted", "in_network", "Riverbend Health", None)
    assert body["document_id"] == card["doc"] and body["member_id"] == "RBH1"
    row = db.execute("select status, payer, member_id from public.patient_insurance where id = %s", (body["id"],)).fetchone()
    assert (row["status"], row["payer"], row["member_id"]) == ("extracted", "Riverbend Health", "RBH1")
    # The vision model got the image itself.
    image_part = fake_llm.prompts["vision"][0][1].content[1]
    assert image_part["image_url"]["url"].startswith("data:image/png;base64,")


def test_unreadable_fields_stay_null(client, card, fake_llm: FakeLLM) -> None:
    fake_llm.replies["vision"] = reading(payer="Riverbend Health", member_id="unknown", group_number="  ")
    body = extract(client, card).json()
    assert (body["member_id"], body["group_number"], body["plan_name"]) == (None, None, None)


def test_reading_again_replaces_the_unconfirmed_read(client, db, card, fake_llm: FakeLLM) -> None:
    first = extract(client, card).json()["id"]
    second = extract(client, card).json()["id"]
    ids = [r["id"] for r in db.execute("select id from public.patient_insurance where patient_id = %s",
                                       (card["patient"],)).fetchall()]
    assert [str(i) for i in ids] == [second] and first != second


def test_only_card_images(client, make: Factory) -> None:
    patient = make.patient()
    pdf = upload(client, patient, "card.pdf", TEST_PDF)
    referral = upload(client, patient, "ref.png", (CARDS / "aja.png").read_bytes(), kind="referral")
    for doc in (pdf, referral):
        resp = client.post(f"/me/documents/{doc}/extract", headers=as_patient(patient))
        assert (resp.status_code, resp.json()["detail"]) == (400, "not_a_card_image")


def test_vision_failure_is_a_502(client, card, fake_llm: FakeLLM) -> None:
    fake_llm.errors["vision"] = RuntimeError("groq down")
    assert (extract(client, card).status_code, extract(client, card).json()["detail"]) == (502, "extraction_failed")
    fake_llm.errors.clear()
    fake_llm.replies["vision"] = "not json at all"
    assert extract(client, card).status_code == 502


def test_another_patients_card_is_404(client, card, make: Factory) -> None:
    other = make.patient()
    assert extract(client, card, other).status_code == 404


# --- confirm and show ---

def test_confirm_with_edits_rechecks_the_network(client, card, fake_llm: FakeLLM) -> None:
    fake_llm.replies["vision"] = reading(payer="Unknown Insurance Co", member_name="Test Patient0")
    read = extract(client, card).json()
    assert read["network"] == "not_on_file"
    resp = client.post(f"/me/insurance/{read['id']}/confirm", headers=as_patient(card["patient"]),
                       json={"payer": "  northstar  ", "member_name": "Test Patient0", "member_id": "NSB9"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["status"], body["network"], body["payer"], body["member_id"]) == (
        "confirmed", "out_of_network", "northstar", "NSB9")
    mine = client.get("/me/insurance", headers=as_patient(card["patient"])).json()
    assert (mine["id"], mine["network"]) == (read["id"], "out_of_network")


def test_confirm_needs_a_payer_and_your_own_row(client, card, make: Factory, fake_llm: FakeLLM) -> None:
    read = extract(client, card).json()
    url = f"/me/insurance/{read['id']}/confirm"
    assert client.post(url, headers=as_patient(card["patient"]), json={"payer": "  "}).status_code == 422
    assert client.post(url, headers=as_patient(make.patient()), json={"payer": "Riverbend"}).status_code == 404


def test_no_insurance_yet_is_null(client, make: Factory) -> None:
    patient = make.patient()
    assert client.get("/me/insurance", headers=as_patient(patient)).json() is None
    assert client.get("/me/insurance").status_code == 401


def test_name_mismatch_warns_but_can_still_confirm(client, card, fake_llm: FakeLLM) -> None:
    fake_llm.replies["vision"] = reading(payer="Riverbend Health", member_name="Somebody Else")
    read = extract(client, card).json()
    assert "Somebody Else" in read["name_warning"] and "Test Patient0" in read["name_warning"]
    done = client.post(f"/me/insurance/{read['id']}/confirm", headers=as_patient(card["patient"]),
                       json={"payer": "Riverbend Health", "member_name": "Somebody Else"}).json()
    assert done["status"] == "confirmed" and done["name_warning"]


# --- plain-code matching ---

@pytest.mark.parametrize(("payer", "plan", "status"), [
    ("Riverbend Health", "Riverbend Silver HMO", "in_network"),
    ("RIVERBEND   health", None, "in_network"),
    ("Riverbend Health Plan", None, "in_network"),  # alias
    ("Liberty Senior", "Liberty Senior Advantage Plus", "in_network"),
    ("Northstar Benefits", "Northstar Essential EPO", "out_of_network"),
    ("Acme Mutual", None, "not_on_file"),
    (None, None, "not_on_file"),
])
def test_network_match(db: psycopg.Connection, payer, plan, status) -> None:
    assert match_network(db, payer, plan).status == status


@pytest.mark.parametrize(("card_name", "ok"), [
    ("Aja Casper", True), ("CASPER, AJA", True), ("Aja M. Casper", True), ("Aja Smith", False), ("", False),
])
def test_name_check(card_name, ok) -> None:
    assert name_matches(card_name, "Aja", "Casper") is ok


def test_norm() -> None:
    assert norm("  RIVERBEND  Health, Inc. ") == "riverbend health inc"


def test_a_read_without_a_payer_is_kept_for_the_patient_to_fill_in(client, db, card, fake_llm: FakeLLM) -> None:
    body = extract(client, card).json()  # the fake vision read nothing at all
    assert (body["payer"], body["network"]) == (None, "not_on_file")
    with pytest.raises(psycopg.errors.CheckViolation):  # but a confirmed row must have a payer
        db.execute("update public.patient_insurance set status = 'confirmed' where id = %s", (body["id"],))
