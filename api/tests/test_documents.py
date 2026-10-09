import time
import uuid

import httpx
import psycopg
import pytest
from fastapi.testclient import TestClient

from app import storage
from app.files import MAX_BYTES, clean_filename
from app.routes import documents as documents_route
from tests.conftest import Factory, as_patient, bearer

JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 64
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n%%EOF\n"


def upload(client: TestClient, patient_id, name: str, data: bytes, kind: str = "insurance_card", ctype: str = "application/octet-stream"):
    return client.post(
        "/me/documents",
        files={"file": (name, data, ctype)},
        data={"kind": kind},
        headers=as_patient(patient_id),
    )


def stored_files(patient_id) -> list[str]:
    """Names of files in the bucket under this patient's folder."""
    resp = storage.client().post(
        f"/object/list/{storage.BUCKET}", json={"prefix": f"{patient_id}/", "limit": 100}
    )
    resp.raise_for_status()
    return [obj["name"] for obj in resp.json()]


def db_rows(db: psycopg.Connection, patient_id) -> list[dict]:
    return db.execute("select * from public.documents where patient_id = %s", (patient_id,)).fetchall()


# --- upload ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "data", "content_type", "ext"),
    [("card.jpg", JPEG, "image/jpeg", "jpg"), ("card.png", PNG, "image/png", "png"), ("ref.pdf", PDF, "application/pdf", "pdf")],
)
def test_upload_each_allowed_type(client, make: Factory, db, name, data, content_type, ext) -> None:
    pat = make.patient()

    resp = upload(client, pat, name, data)

    assert resp.status_code == 201
    body = resp.json()
    assert (body["content_type"], body["size_bytes"], body["original_filename"]) == (content_type, len(data), name)
    [row] = db_rows(db, pat)
    assert row["storage_path"] == f"{pat}/{body['id']}.{ext}"
    assert stored_files(pat) == [f"{body['id']}.{ext}"]


def test_type_comes_from_bytes_not_extension(client, make: Factory) -> None:
    """A PNG named .pdf is stored as a PNG."""
    pat = make.patient()
    resp = upload(client, pat, "looks-like.pdf", PNG, ctype="application/pdf")
    assert (resp.status_code, resp.json()["content_type"]) == (201, "image/png")


def test_wrong_type_is_400(client, make: Factory, db) -> None:
    pat = make.patient()
    resp = upload(client, pat, "notes.txt", b"hello, this is text", ctype="text/plain")
    assert (resp.status_code, resp.json()["detail"]) == (400, "unsupported_type")
    assert db_rows(db, pat) == [] and stored_files(pat) == []


def test_fake_extension_is_400(client, make: Factory) -> None:
    """A .txt renamed .png (and claiming image/png) is still rejected."""
    resp = upload(client, make.patient(), "photo.png", b"just some text", ctype="image/png")
    assert (resp.status_code, resp.json()["detail"]) == (400, "unsupported_type")


def test_empty_file_is_400(client, make: Factory) -> None:
    resp = upload(client, make.patient(), "empty.png", b"")
    assert (resp.status_code, resp.json()["detail"]) == (400, "empty_file")


def test_too_large_is_413(client, make: Factory, db) -> None:
    pat = make.patient()
    resp = upload(client, pat, "huge.png", PNG + b"\x00" * (MAX_BYTES + 1 - len(PNG)))
    assert (resp.status_code, resp.json()["detail"]) == (413, "file_too_large")
    assert db_rows(db, pat) == [] and stored_files(pat) == []


def test_exactly_max_size_is_allowed(client, make: Factory) -> None:
    resp = upload(client, make.patient(), "max.png", PNG + b"\x00" * (MAX_BYTES - len(PNG)))
    assert resp.status_code == 201


def test_bad_kind_is_422(client, make: Factory) -> None:
    assert upload(client, make.patient(), "x.png", PNG, kind="selfie").status_code == 422


def test_filename_is_sanitized(client, make: Factory) -> None:
    pat = make.patient()
    assert upload(client, pat, "../../x.png", PNG).json()["original_filename"] == "x.png"
    assert upload(client, pat, "C:\\Users\\me\\card.png", PNG).json()["original_filename"] == "card.png"
    long_name = "a" * 300 + ".png"
    assert upload(client, pat, long_name, PNG).json()["original_filename"] == "a" * 196 + ".png"


def test_clean_filename_edge_cases() -> None:
    assert clean_filename("../../x.png") == "x.png"
    assert clean_filename("..") == "document"
    assert clean_filename(None) == "document"
    assert clean_filename("bad\x00name\n.png") == "badname.png"
    assert len(clean_filename("b" * 500)) == 200


# --- list, view, delete ---------------------------------------------------------


def test_list_is_newest_first_and_only_yours(client, make: Factory) -> None:
    aja, bart = make.patient(), make.patient()
    first = upload(client, aja, "first.png", PNG).json()["id"]
    second = upload(client, aja, "second.pdf", PDF, kind="referral").json()["id"]
    upload(client, bart, "barts.png", PNG)

    mine = client.get("/me/documents", headers=as_patient(aja)).json()

    assert [d["id"] for d in mine] == [second, first]


def test_signed_url_works_then_expires(client, make: Factory, monkeypatch) -> None:
    pat = make.patient()
    doc = upload(client, pat, "card.png", PNG).json()["id"]

    resp = client.get(f"/me/documents/{doc}/url", headers=as_patient(pat))
    assert resp.status_code == 200 and resp.json()["expires_in"] == 60
    fetched = httpx.get(resp.json()["url"])
    assert (fetched.status_code, fetched.content) == (200, PNG)

    monkeypatch.setattr(storage, "SIGNED_URL_SECONDS", 1)
    short = client.get(f"/me/documents/{doc}/url", headers=as_patient(pat)).json()["url"]
    time.sleep(2.5)
    assert httpx.get(short).status_code >= 400


def test_other_patient_cannot_view_or_delete(client, make: Factory, db) -> None:
    aja, bart = make.patient(), make.patient()
    doc = upload(client, aja, "card.png", PNG).json()["id"]

    view = client.get(f"/me/documents/{doc}/url", headers=as_patient(bart))
    delete = client.delete(f"/me/documents/{doc}", headers=as_patient(bart))
    missing = client.get(f"/me/documents/{uuid.uuid4()}/url", headers=as_patient(bart))

    # Same response as a document that doesn't exist: nothing reveals Aja's file.
    assert view.status_code == delete.status_code == missing.status_code == 404
    assert view.json() == delete.json() == missing.json() == {"detail": "document_not_found"}
    assert len(db_rows(db, aja)) == 1 and len(stored_files(aja)) == 1


def test_delete_removes_file_and_row(client, make: Factory, db) -> None:
    pat = make.patient()
    doc = upload(client, pat, "ref.pdf", PDF, kind="referral").json()["id"]

    resp = client.delete(f"/me/documents/{doc}", headers=as_patient(pat))

    assert resp.status_code == 204
    assert db_rows(db, pat) == [] and stored_files(pat) == []
    again = client.delete(f"/me/documents/{doc}", headers=as_patient(pat))
    assert again.status_code == 404


def test_staff_and_anonymous_are_refused(client, make: Factory) -> None:
    staff = bearer(make.staff_token())
    assert client.get("/me/documents", headers=staff).status_code == 403
    assert client.get("/me/documents").status_code == 401


# --- no orphans -------------------------------------------------------------------


def test_db_insert_failure_removes_uploaded_file(client, make: Factory, db, monkeypatch) -> None:
    pat = make.patient()
    monkeypatch.setattr(documents_route, "INSERT_SQL", "insert into public.no_such_table values (%s,%s,%s,%s,%s,%s,%s)")

    resp = upload(client, pat, "card.png", PNG)

    assert resp.status_code == 500
    assert db_rows(db, pat) == [] and stored_files(pat) == []


def test_storage_failure_writes_no_row(client, make: Factory, db, monkeypatch) -> None:
    pat = make.patient()

    def broken_upload(*args, **kwargs):
        raise storage.StorageError("storage is down")

    monkeypatch.setattr(storage, "upload", broken_upload)

    resp = upload(client, pat, "card.png", PNG)

    assert resp.status_code == 500
    assert db_rows(db, pat) == [] and stored_files(pat) == []


def test_storage_delete_failure_keeps_row(client, make: Factory, db, monkeypatch) -> None:
    pat = make.patient()
    doc = upload(client, pat, "card.png", PNG).json()["id"]

    def broken_remove(*args, **kwargs):
        raise storage.StorageError("storage is down")

    monkeypatch.setattr(storage, "remove", broken_remove)
    resp = client.delete(f"/me/documents/{doc}", headers=as_patient(pat))
    monkeypatch.undo()

    assert resp.status_code == 500
    assert len(db_rows(db, pat)) == 1 and len(stored_files(pat)) == 1


def test_browser_keys_cannot_read_documents_or_bucket(client, make: Factory, supabase_auth) -> None:
    pat = make.patient()
    doc = upload(client, pat, "card.png", PNG).json()
    base = supabase_auth.url.removesuffix("/auth/v1")
    path = f"{pat}/{doc['id']}.png"
    for headers in ({"apikey": supabase_auth.anon_key}, {"apikey": supabase_auth.anon_key, **as_patient(pat)}):
        rows = httpx.get(f"{base}/rest/v1/documents?select=*", headers=headers)
        assert (rows.status_code, rows.json()) == (200, [])
        file = httpx.get(f"{base}/storage/v1/object/patient-docs/{path}", headers=headers)
        assert file.status_code >= 400
        listing = httpx.post(f"{base}/storage/v1/object/list/patient-docs", headers=headers, json={"prefix": f"{pat}/"})
        assert listing.status_code >= 400 or listing.json() == []
