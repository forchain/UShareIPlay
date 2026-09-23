from tortoise import fields
from tortoise.models import Model


class UserChatLog(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField('models.User', related_name='chat_logs')
    content = fields.TextField()
    created_at = fields.DatetimeField(auto_now_add=True, db_index=True)

    class Meta:
        table = "user_chat_logs"

    def __str__(self):
        return f"UserChatLog(id={self.id}, user_id={self.user_id}, created_at={self.created_at})"
