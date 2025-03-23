from tortoise import fields, models
from tortoise.models import Model
from .user import User

class SeatReservation(Model):
    id = fields.IntField(pk=True)
    user = fields.ForeignKeyField('models.User', related_name='reservations')
    seat_number = fields.IntField()
    start_time = fields.DatetimeField()
    duration_hours = fields.IntField()  # Duration in hours
    created_at = fields.DatetimeField(auto_now_add=True)
    updated_at = fields.DatetimeField(auto_now=True)

    class Meta:
        table = "seat_reservations" 