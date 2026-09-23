import json
from functools import partial
from tortoise import fields
from tortoise.models import Model

# Persist JSON as unescaped UTF-8 without \uXXXX escaping for easier direct database inspection and editing
_json_dumps_utf8 = partial(json.dumps, ensure_ascii=False, separators=(',', ':'))


class UserMemory(Model):
    id = fields.IntField(pk=True)
    user = fields.OneToOneField('models.User', related_name='memory')
    immutable_directives = fields.JSONField(
        default=list,
        encoder=_json_dumps_utf8,
    )  # list of strings (e.g. ["称谓: 浩哥", "硬性偏好: 喜好周杰伦"])
    profile_summary = fields.TextField(default="")  # evolving background / taste summary
    last_consolidated_at = fields.DatetimeField(null=True)
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "user_memories"

    def __str__(self):
        return f"UserMemory(id={self.id}, user_id={self.user_id}, last_consolidated_at={self.last_consolidated_at})"
