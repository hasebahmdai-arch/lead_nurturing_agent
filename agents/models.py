from __future__ import annotations

import hashlib

from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils import timezone

from crm.models import ProjectName

brochure_storage = FileSystemStorage(location=settings.BROCHURE_UPLOAD_DIR)


class BrochureDocument(models.Model):
    project_name = models.CharField(max_length=64, choices=ProjectName.choices, blank=True)
    original_name = models.CharField(max_length=255)
    file = models.FileField(upload_to="", storage=brochure_storage)
    checksum = models.CharField(max_length=64, editable=False)
    content_type = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="uploaded_brochures",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    last_indexed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-uploaded_at",)

    def save(self, *args, **kwargs):
        if self.file and not self.checksum:
            hasher = hashlib.sha256()
            position = self.file.tell() if hasattr(self.file, "tell") else None
            self.file.open("rb")
            for chunk in iter(lambda: self.file.read(8192), b""):
                hasher.update(chunk)
            self.file.close()
            if position is not None:
                try:
                    self.file.seek(position)
                except (OSError, ValueError):
                    pass
            self.checksum = hasher.hexdigest()
        super().save(*args, **kwargs)

    def mark_indexed(self):
        self.last_indexed_at = timezone.now()
        self.save(update_fields=["last_indexed_at"])

    def __str__(self):
        return f"{self.original_name} ({self.project_name or 'Unassigned'})"


class DocumentIngestionLog(models.Model):
    document = models.ForeignKey(BrochureDocument, related_name="ingestion_logs", on_delete=models.CASCADE)
    status = models.CharField(max_length=32)
    detail = models.TextField(blank=True)
    chunks_indexed = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-created_at",)
