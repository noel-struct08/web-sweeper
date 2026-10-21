# chat/consumers.py
import json, asyncio, random
from datetime import timedelta

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.db import IntegrityError, transaction
from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone

from .helpers import process_move, generate_cells, create_next_board
from .models import User, Board, Cell, Board_Participation, Room


class ChatConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        print("CONNECT")

        self.room_id = self.scope["url_route"]["kwargs"]["room_id"]
        self.room_group_id = f"room_{self.room_id}"
        self.user = self.scope['user']

        # retrieve the current board  in a room 
        board = await Board.objects.aget(room_id=self.room_id,is_finished=False)
        self.board = board
        self.allowed_moves = ['flag', 'unflag', 'reveal']

        # Join room group
        await self.channel_layer.group_add(self.room_group_id, self.channel_name,)
        await self.accept() 
        reveal_all = board.is_finished

        # Send on-going board cells only to connected user
        await self.send(text_data=json.dumps({"type": "board.new", "board_id": self.board.id, "cells": await database_sync_to_async(board.serialize_cells)(reveal_all) }))
        # updates player status list when someone enters, including the newly connected user
        await self.channel_layer.group_send(
            self.room_group_id, {"type": "player.render", "participants": await database_sync_to_async(board.serialize_participants)()}
        )

    async def disconnect(self, close_code):
        print("DISCONNECT", close_code)
        # updates player status list when someone leaves
        await self.channel_layer.group_discard(self.room_group_id, self.channel_name)
        await self.channel_layer.group_send(
            self.room_group_id, {"type": "player.render", "participants": await database_sync_to_async(self.board.serialize_participants)()}
        )

    # Receive message from WebSocket
    async def receive(self, text_data): 
        text_data_json = json.loads(text_data)
        function = text_data_json["function"]
        self.board = await Board.objects.aget(pk=self.board.id)

        # checks if user is still active in current room 
        participation = await Board_Participation.objects.aget(board=self.board, user=self.user)
        if participation.has_left:
            await self.close()
            return
        
        if function == "ping":
            # updates database for user's last_seen for every ping
            participation.last_seen = timezone.now()
            await participation.asave()
            # update player for every ping
            await self.channel_layer.group_send(
                self.room_group_id, {"type": "player.render", "participants": await database_sync_to_async(self.board.serialize_participants)()} 
            )
            return
    
        # database altering functions needs to be called here in the receive function
        if function == "board_update": 
            # prevents spam clicks from spamming the database
            if timezone.now() - participation.last_seen > timedelta(seconds=5):
                participation.last_seen = timezone.now()
                await participation.asave()
                # update player for every ping
                await self.channel_layer.group_send(
                    self.room_group_id, {"type": "player.render", "participants": await database_sync_to_async(self.board.serialize_participants)()} 
                )
                
            if self.board.is_finished == True or participation.status != 'active':
                return
            board_id = int(text_data_json['board_id'])
            # prevents click during the 5-second delay to affect the next board
            if board_id != self.board.id:
                return
            row = int(text_data_json['row'])
            col = int(text_data_json['col'])
            move = text_data_json['move']
            if not self.board.is_generated and move != "reveal":
                return
            # identifies sent data regarding move and returns if invalid
            if not (0 <= row <= 29 ) or not (0 <= col <= 15) or move not in self.allowed_moves:
                return
            # returns a booelean to check whether a user's move has finished a board, also prevents other consumers from creating additional boards
            move_status = await database_sync_to_async(process_move)(row,col,move,self.board.id)
            # prevents two users from finishing a board simultaneously
            if not move_status:
                return
            # update the board object of the consumer since the is_finished attribute could change after process_move
            self.board = await Board.objects.aget(pk=self.board.id) 
            
            # Send updated board cells to room group
            await self.channel_layer.group_send(
                self.room_group_id, {
                    "type": "board.render", 
                    "cells": await database_sync_to_async(self.board.serialize_cells)(move_status['reveal_all']), 
                    "move_status": move_status
                }
            )
          

            if self.board.is_finished == True:
               asyncio.create_task(self.transfer_board(self.board, self.room_id))
               
    async def transfer_board(self, board, room):
        try:
            # pause and let users see finished board for a while
            await asyncio.sleep(10)
            new_board = await database_sync_to_async(create_next_board)(board, room)
            # Send new board  to room group
            await self.channel_layer.group_send(
                self.room_group_id, {"type": "board.new", "board_id": new_board.id, "cells": await database_sync_to_async(new_board.serialize_cells)(False)}
            )
            # update player list to transferred players
            await self.channel_layer.group_send(
                self.room_group_id, {"type": "player.render", "participants": await database_sync_to_async(new_board.serialize_participants)()} 
            )
        except asyncio.CancelledError:
            raise
        except Exception as e:
            print(f"Board Transfer Failed: {e}")
            # notify group of error
            await self.channel_layer.group_send(text_data=json.dumps({
                "type": "room.failed"
            }))
            Room.objects.get(pk=self.room_id).delete()
    
    async def board_render(self, event):
        cells = event["cells"]
        move_status = event["move_status"]
        await self.send(text_data=json.dumps({"type": "board.render", "cells": cells, "move_status": move_status}))

    async def player_render(self, event):
        participants = event["participants"]
        await self.send(text_data=json.dumps({"type": "player.render", "participants": participants}))  

    async def board_new(self, event):
        board_id= event["board_id"]
        cells = event["cells"]
        # overwrite new board of the consumer class
        self.board = await Board.objects.aget(pk=board_id)
        updated_participation = await Board_Participation.objects.aget(user=self.user,board=self.board)
        # updates can_play status when a new board loads in
        if updated_participation.status == 'active':
            self.can_play = True
        else:
            self.can_play = False

        # tells js or the client side to render new board
        await self.send(text_data=json.dumps({"type": "board.new", "board_id": self.board.id, "cells": cells }))
