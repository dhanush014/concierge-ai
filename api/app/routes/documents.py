"""Patient documents: upload, list, view (signed URL), delete. Storage only, no AI.

A document that isn't yours gets the same 404 as one that doesn't exist.
"""

import logging
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Form, HTTPException, Response, UploadFile

from app import storage
from app.db import Conn
from app.deps import get_current_patient
from app.files import MAX_BYTES, clean_filename, detect_type, read_limited
from app.models import Document, SignedUrl
from app.queries import DOCUMENT_COLUMNS as COLUMNS, my_documents

router = APIRouter(prefix="/me/documents", tags=["documents"])
log = logging.getLogger(__name__)

PatientId = Annotated[UUID, Depends(get_current_patient)]
Kind = Literal["insurance_card", "referral"]

INSERT_SQL = f"""
    insert into public.documents
      (id, patient_id, kind, storage_path, original_filename, content_type, size_bytes)
    values (%s, %s, %s, %s, %s, %s, %s)
    returning {COLUMNS}
"""

NOT_FOUND = HTTPException(status_code=404, detail="document_not_found")
STORAGE_FAILED = HTTPException(status_code=500, detail="Internal server error")


@router.post("", status_code=201)
def upload_document(
    conn: Conn, patient_id: PatientId, file: UploadFile, kind: Annotated[Kind, Form()]
) -> Document:
    data = read_limited(file)
    if not data:
        raise HTTPException(status_code=400, detail="empty_file")
    if len(data) > MAX_BYTES:
        raise HTTPException(status_code=413, detail="file_too_large")
    detected = detect_type(data)
    if detected is None:
        raise HTTPException(status_code=400, detail="unsupported_type")
    content_type, ext = detected

    doc_id = uuid4()
    path = f"{patient_id}/{doc_id}.{ext}"
    try:
        storage.upload(path, data, content_type)
    except storage.StorageError:
        log.exception("Storage upload failed")
        raise STORAGE_FAILED from None  # nothing was written to the database

    try:
        row = conn.execute(
            INSERT_SQL,
            (doc_id, patient_id, kind, path, clean_filename(file.filename), content_type, len(data)),
        ).fetchone()
        conn.commit()  # commit here so a failure is caught and the file cleaned up
    except Exception:
        conn.rollback()
        try:
            storage.remove(path)
        except storage.StorageError:
            log.exception("Could not remove orphan file %s", path)
        raise
    return Document(**row)


@router.get("")
def list_documents(conn: Conn, patient_id: PatientId) -> list[Document]:
    return my_documents(conn, patient_id)


@router.get("/{document_id}/url")
def document_url(conn: Conn, patient_id: PatientId, document_id: UUID) -> SignedUrl:
    row = conn.execute(
        "select storage_path from public.documents where id = %s and patient_id = %s",
        (document_id, patient_id),
    ).fetchone()
    if row is None:
        raise NOT_FOUND
    try:
        url = storage.signed_url(row["storage_path"])
    except storage.StorageError:
        log.exception("Could not sign URL")
        raise STORAGE_FAILED from None
    return SignedUrl(url=url, expires_in=storage.SIGNED_URL_SECONDS)


@router.delete("/{document_id}", status_code=204, response_class=Response)
def delete_document(conn: Conn, patient_id: PatientId, document_id: UUID) -> Response:
    row = conn.execute(
        "delete from public.documents where id = %s and patient_id = %s returning storage_path",
        (document_id, patient_id),
    ).fetchone()
    if row is None:
        raise NOT_FOUND
    try:
        storage.remove(row["storage_path"])
    except storage.StorageError:
        conn.rollback()  # keep the row: the file is still there
        log.exception("Storage delete failed")
        raise STORAGE_FAILED from None
    conn.commit()
    return Response(status_code=204)
