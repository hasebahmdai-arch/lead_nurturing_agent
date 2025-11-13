from django.contrib import admin

from .models import BrochureDocument, DocumentIngestionLog


class DocumentIngestionLogInline(admin.TabularInline):
    model = DocumentIngestionLog
    extra = 0
    readonly_fields = ("status", "detail", "chunks_indexed", "created_at")


@admin.register(BrochureDocument)
class BrochureDocumentAdmin(admin.ModelAdmin):
    list_display = ("original_name", "project_name", "uploaded_by", "uploaded_at", "last_indexed_at")
    search_fields = ("original_name", "project_name", "checksum")
    list_filter = ("project_name",)
    inlines = [DocumentIngestionLogInline]


@admin.register(DocumentIngestionLog)
class DocumentIngestionLogAdmin(admin.ModelAdmin):
    list_display = ("document", "status", "chunks_indexed", "created_at")
    list_filter = ("status",)
    search_fields = ("document__original_name",)
