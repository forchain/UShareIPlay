from tortoise import fields
from tortoise.models import Model


class ExitEvent(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField('models.User', related_name='exit_events')
    command = fields.TextField()  # 命令字符串，如 ":play 歌曲名"
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "exit_events"

    def __str__(self):
        return f"ExitEvent(id={self.id}, user={self.user_id}, command={self.command})"
