from __future__ import annotations

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from django.core.files.base import ContentFile

from agents.ingestion import IngestionOutcome
from agents.models import BrochureDocument


class StubIngestionService:
    def __init__(self):
        self.last_brochure = None

    def store_upload(self, *, uploaded_file, project_name, content_type, user):
        content = uploaded_file.read()
        brochure = BrochureDocument.objects.create(
            project_name=project_name or "",
            original_name=uploaded_file.name,
            file=ContentFile(content, name=uploaded_file.name),
            content_type=content_type or "text/plain",
            uploaded_by=user if getattr(user, "is_authenticated", False) else None,
        )
        self.last_brochure = brochure
        return brochure

    def ingest(self, brochure):
        return IngestionOutcome(chunks_indexed=3, collection_name="project_altura")


@pytest.mark.django_db
def test_document_ingestion_endpoint(auth_client, monkeypatch):
    stub_service = StubIngestionService()
    monkeypatch.setattr("agents.api.get_ingestion_service", lambda: stub_service)

    upload = SimpleUploadedFile("brochure.txt", b"Sample brochure content", content_type="text/plain")
    response = auth_client.post("/api/agent/documents/upload?project_name=Altura", {"files": upload})
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data[0]["project_name"] == "Altura"
    assert data[0]["chunks_indexed"] == 3
    assert stub_service.last_brochure is not None

