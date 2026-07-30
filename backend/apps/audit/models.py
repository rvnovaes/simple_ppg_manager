"""Trilha de auditoria: quem, quando, o quê, alvo.

O alvo é guardado como par de strings (app.model + pk) em vez de
GenericForeignKey de propósito: o registro precisa sobreviver à exclusão do
objeto referenciado — auditoria que some junto com o dado não audita nada.

Ninguém cria AuditLog direto; use apps.core.audit.record().
"""

from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    program = models.ForeignKey(
        "programs.Program",
        on_delete=models.PROTECT,
        related_name="audit_logs",
        null=True,
        blank=True,
        verbose_name="programa",
        help_text="Nulo em eventos que não pertencem a um programa (ex.: login).",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        related_name="audit_logs",
        null=True,
        blank=True,
        verbose_name="autor",
    )
    event = models.CharField("evento", max_length=100, db_index=True)
    target_type = models.CharField("tipo do alvo", max_length=100, blank=True)
    target_id = models.CharField("id do alvo", max_length=64, blank=True)
    payload = models.JSONField("detalhes", default=dict, blank=True)
    created_at = models.DateTimeField("quando", auto_now_add=True, db_index=True)

    class Meta:
        verbose_name = "registro de auditoria"
        verbose_name_plural = "registros de auditoria"
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["target_type", "target_id"])]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M} {self.event}"
