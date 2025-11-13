from django.contrib import admin

from .models import Lead


@admin.register(Lead)
class LeadAdmin(admin.ModelAdmin):
    list_display = ("crm_id", "full_name", "email", "project_enquired", "status", "last_conversation_date")
    search_fields = ("crm_id", "first_name", "last_name", "email", "phone_number")
    list_filter = ("project_enquired", "status", "unit_type")
