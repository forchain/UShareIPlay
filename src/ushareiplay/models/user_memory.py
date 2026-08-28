from tortoise import fields
from tortoise.models import Model


class UserMemory(Model):
    id = fields.IntField(pk=True)
    user = fields.OneToOneField('models.User', related_name='memory')
    immutable_directives = fields.JSONField(default=list)  # list of strings (e.g. ["称谓: 浩哥", "硬性偏好: 喜好周杰伦"])
    profile_summary = fields.TextField(default="")  # evolving background / taste summary
    last_consolidated_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "user_memories"

    def __str__(self):
        return f"UserMemory(id={self.id}, user_id={self.user_id}, last_consolidated_at={self.last_consolidated_at})"
