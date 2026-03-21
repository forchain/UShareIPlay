from tortoise import fields
from tortoise.models import Model


class Timer(Model):
    id = fields.IntField(pk=True)
    key = fields.CharField(max_length=255, unique=True)
    message = fields.TextField()
    target_time = fields.CharField(max_length=8)
    repeat = fields.BooleanField(default=False)
    enabled = fields.BooleanField(default=True)
    next_trigger = fields.DatetimeField(null=True)

    class Meta:
        table = "timer_events"

    def __str__(self):
        return f"Timer(key={self.key}, target_time={self.target_time}, enabled={self.enabled})"
