from django.contrib import admin

from .models import Campaign, CampaignLead, ConversationMessage


class CampaignLeadInline(admin.TabularInline):
    model = CampaignLead
    extra = 0
    readonly_fields = ("lead", "status", "goal_outcome", "dispatch_time")


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("name", "project_name", "message_channel", "created_by", "created_at")
    list_filter = ("project_name", "message_channel")
    search_fields = ("name",)
    inlines = [CampaignLeadInline]


@admin.register(CampaignLead)
class CampaignLeadAdmin(admin.ModelAdmin):
    list_display = ("campaign", "lead", "status", "goal_outcome", "dispatch_time")
    list_filter = ("status", "goal_outcome")
    search_fields = ("lead__first_name", "lead__last_name", "campaign__name")


@admin.register(ConversationMessage)
class ConversationMessageAdmin(admin.ModelAdmin):
    list_display = ("campaign_lead", "sender", "intent", "created_at")
    list_filter = ("sender", "intent")
    search_fields = ("campaign_lead__lead__first_name", "campaign_lead__lead__last_name", "message")
