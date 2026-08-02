from tortoise import fields
from tortoise.models import Model


class ReceiveEvent(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField("models.User", related_name="receive_events")
    command = fields.TextField()
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "receive_events"

    def __str__(self):
        return f"ReceiveEvent(id={self.id}, user={self.user_id}, command={self.command})"
