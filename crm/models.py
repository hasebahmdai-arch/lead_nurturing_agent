from __future__ import annotations

from django.contrib.auth import get_user_model
from django.db import models
from django.utils import timezone


class ProjectName(models.TextChoices):
    ALTURA = "Altura", "Altura"
    BEACHGATE = "Beachgate by Address", "Beachgate by Address"
    DAMAC_BAY = "Damac Bay by Cavalli", "Damac Bay by Cavalli"
    DLF_WEST_PARK = "DLF West Park", "DLF West Park"
    GODREJ_VISTAS = "Godrej Vistas", "Godrej Vistas"
    LUMINA_GRAND = "Lumina Grand", "Lumina Grand"
    SOBHA_CREST = "Sobha Crest", "Sobha Crest"
    SOBHA_WAVES = "Sobha Waves", "Sobha Waves"


class UnitType(models.TextChoices):
    STUDIO = "studio", "Studio"
    ONE_BED = "1 bed", "1 Bed"
    TWO_BED = "2 bed", "2 Bed"
    TWO_BED_STUDY = "2 bed w study", "2 Bed with Study"
    THREE_BED = "3 bed", "3 Bed"
    FOUR_BED = "4 bed", "4 Bed"
    DUPLEX = "duplex", "Duplex"
    PENTHOUSE = "penthouse", "Penthouse"


class LeadStatus(models.TextChoices):
    NOT_CONNECTED = "not_connected", "Not Connected"
    CONNECTED = "connected", "Connected"
    VISIT_SCHEDULED = "visit_scheduled", "Visit Scheduled"
    VISIT_DONE_NOT_PURCHASED = "visit_done_not_purchased", "Visit Done Not Purchased"
    PURCHASED = "purchased", "Purchased"
    NOT_INTERESTED = "not_interested", "Not Interested"


class LeadQuerySet(models.QuerySet):
    def shortlist(self, *, project_names=None, unit_types=None, lead_status=None,
                  last_conversation_from=None, last_conversation_to=None,
                  budget_min=None, budget_max=None):
        queryset = self

        if project_names:
            queryset = queryset.filter(project_enquired__in=project_names)

        if unit_types:
            queryset = queryset.filter(unit_type__in=unit_types)

        if lead_status:
            queryset = queryset.filter(status=lead_status)

        if last_conversation_from:
            queryset = queryset.filter(last_conversation_date__gte=last_conversation_from)

        if last_conversation_to:
            queryset = queryset.filter(last_conversation_date__lte=last_conversation_to)

        if budget_min is not None or budget_max is not None:
            min_value = budget_min if budget_min is not None else 0
            max_value = budget_max if budget_max is not None else float("inf")
            queryset = queryset.filter(
                models.Q(budget_min__isnull=True, budget_max__isnull=True)
                | (
                    models.Q(budget_min__lte=max_value)
                    & models.Q(budget_max__gte=min_value)
                )
            )

        return queryset


class LeadManager(models.Manager):
    def get_queryset(self):
        return LeadQuerySet(self.model, using=self._db)

    def shortlist(self, **kwargs):
        return self.get_queryset().shortlist(**kwargs)


class Lead(models.Model):
    user = models.ForeignKey(
        get_user_model(),
        related_name="managed_leads",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        help_text="Owner within the sales team."
    )
    crm_id = models.CharField(max_length=64, unique=True)
    first_name = models.CharField(max_length=120)
    last_name = models.CharField(max_length=120, blank=True)
    email = models.EmailField(unique=True)
    phone_number = models.CharField(max_length=32, blank=True)

    project_enquired = models.CharField(max_length=64, choices=ProjectName.choices)
    unit_type = models.CharField(max_length=32, choices=UnitType.choices)
    status = models.CharField(max_length=64, choices=LeadStatus.choices, default=LeadStatus.NOT_CONNECTED)

    budget_min = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    budget_max = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    family_size = models.PositiveIntegerField(null=True, blank=True)
    location_preference = models.CharField(max_length=128, blank=True)
    purchase_motive = models.CharField(max_length=256, blank=True)
    financing_readiness = models.CharField(max_length=128, blank=True)
    profile_metadata = models.JSONField(default=dict, blank=True)

    last_conversation_date = models.DateField(null=True, blank=True)
    last_conversation_summary = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = LeadManager()

    class Meta:
        ordering = ("-updated_at",)

    def __str__(self):
        return f"{self.full_name} ({self.email})"

    @property
    def full_name(self) -> str:
        return " ".join(filter(None, [self.first_name, self.last_name]))

    def mark_connected(self):
        self.status = LeadStatus.CONNECTED
        self.save(update_fields=["status", "updated_at"])

    def record_conversation(self, summary: str, *, occurred_at=None):
        self.last_conversation_summary = summary
        self.last_conversation_date = occurred_at or timezone.now().date()
        self.save(update_fields=["last_conversation_summary", "last_conversation_date", "updated_at"])
