from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from django.db import models
import time
from datetime import datetime, timedelta
# Create your models here.

class User(AbstractUser):
    wins = models.IntegerField(default=0)
    games_played = models.IntegerField(default=0)

class Room(models.Model):
    room_name = models.TextField()

class Board(models.Model):
    # content, poster, date_posted, likes
    version_number = models.IntegerField(default=1)
    room = models.ForeignKey(Room, related_name='boards', on_delete=models.CASCADE, default=None)
    is_finished = models.BooleanField(default=False)
    is_generated = models.BooleanField(default=False)
    
    # filters data to be sent to the client
    def serialize_cells(self, reveal_all):
        return {
            'board_id': self.id,
            'cells': [
                {
                    'row': cell.row,
                    'col': cell.col,
                    'is_revealed': cell.is_revealed,
                    'is_flagged': cell.is_flagged,
                    'value': 'is_mine' if cell.is_mine and reveal_all 
                    else cell.value if cell.is_revealed 
                    else None
                     
                }
                for cell in self.cells.all()
            ]  
        }
    
    def serialize_participants(self):
        return {
            'players': [
                {
                    'username': participant.user.username,
                    'status': participant.status,
                    'wins': participant.user.wins,
                    'online': True if participant.last_seen >= (timezone.now() - timedelta(seconds=35))
                    else False
                }
                for participant in self.participations.all()
            ]  
        }
        pass
        
class Board_Participation(models.Model):
    # content, poster, date_posted, likes
    user = models.ForeignKey(User, related_name="participations", on_delete=models.CASCADE)
    board = models.ForeignKey(Board, related_name="participations", on_delete=models.CASCADE)
    status = models.TextField(default="active")
    last_seen = models.DateTimeField(default=datetime.now)
    has_left = models.BooleanField(default=False)

class Cell(models.Model):
    # content, poster, date_posted, likes
    board = models.ForeignKey(Board, related_name="cells", on_delete=models.CASCADE)
    row = models.IntegerField()
    col = models.IntegerField() 
    is_mine = models.BooleanField(default=False)
    is_revealed = models.BooleanField(default=False)
    is_flagged = models.BooleanField(default=False)
    value = models.IntegerField(null = True, default=None, blank=True)

   