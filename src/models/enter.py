from tortoise import fields
from tortoise.models import Model


class Enter(Model):
    id = fields.IntField(pk=True)
    username = fields.CharField(max_length=255, index=True)
    command = fields.TextField()  # 命令字符串，如 ":play 歌曲名"
    created_at = fields.DatetimeField(auto_now_add=True)

    class Meta:
        table = "enter"

    def __str__(self):
        return f"Enter(id={self.id}, username={self.username}, command={self.command})"
