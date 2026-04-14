from tortoise import fields, models
from tortoise.models import Model

class User(Model):
    id = fields.IntField(pk=True)
    username = fields.CharField(max_length=255, unique=True, index=True)
    level = fields.IntField(default=0)  # Default level is 0
    canonical_user = fields.ForeignKeyField(
        'models.User',
        related_name='aliases',
        null=True,
        on_delete=fields.SET_NULL,
    )
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "users" 