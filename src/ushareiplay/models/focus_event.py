from tortoise import fields
from tortoise.models import Model


class FocusEvent(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField("models.User", related_name="focus_events")
    command = fields.TextField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "focus_events"

    def __str__(self):
        return f"FocusEvent(id={self.id}, user={self.user_id}, command={self.command})"
