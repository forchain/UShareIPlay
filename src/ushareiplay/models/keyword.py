from tortoise import fields
from tortoise.models import Model


class Keyword(Model):
    id = fields.IntField(pk=True)
    keyword = fields.CharField(max_length=255, index=True)
    command = fields.TextField()  # 支持多条命令用 ; 分隔
    creator = fields.ForeignKeyField('models.User', related_name='keywords', null=True)
    is_public = fields.BooleanField(default=True)  # True=所有人可执行，False=仅创建者
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "keywords"
        
    def __str__(self):
        source = "config" if self.creator_id is None else "user"
        return f"Keyword({self.keyword}, source={source})"
