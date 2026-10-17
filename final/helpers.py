from .models import User, Board, Cell, Board_Participation
from django.db import transaction, IntegrityError
from django.core.exceptions import ObjectDoesNotExist
from datetime import timedelta
from django.utils import timezone

import random

# open a transaction
@transaction.atomic
def process_move(row,col,move,board_id):
    # load and lock board to only allow one move at a time (prevents race conditions, especially with floodfills)
    board_model = Board.objects.select_for_update().get(pk=board_id)
    # doesn't allow clicks after a previous move had finished the board
    if board_model.is_finished or not board_model.is_generated:
        return False
    elif move == 'reveal':
        # initialize board
        board = {}
        for i in range(30):
            board[i] = {}
        cells = Cell.objects.filter(board=board_id)
        for cell in cells:
            board[cell.row][cell.col] = {
                'is_revealed': cell.is_revealed,
                "is_mine": cell.is_mine, 
                "value": cell.value,
            } 
        # check if clicked cell is mine before floodfill
        # if lose
        if board[row][col]['is_mine']:
            clicked_cell = Cell.objects.get(row=row,col=col,board=board_model)
            clicked_cell.is_revealed = True
            clicked_cell.save()
            # update players' status
            update_players_status(board_model, 'lose')
            # returns True if game ended
            board_model.save()
            return {
                "status": "lose",
                "reveal_all": True,
            }

        else:
            check_floodfills(row,col,board)
            for cell in cells:
                cell.is_revealed = board[cell.row][cell.col]['is_revealed']
            Cell.objects.bulk_update(cells, ['is_revealed']) 

            # add win conditions
            win = True
            for i in range(30):
                for j in range(16):
                    if not board[i][j]['is_mine'] and not board[i][j]['is_revealed']:
                        win = False
                        break
                    if not win:
                        break
            if win:
                # update players' status
                update_players_status(board_model, 'win')
                # returns True if game ended
                board_model.save()
                return {
                    "status": "win",
                    "reveal_all": True,
                }
    elif move == 'flag':
        try:
            cell = Cell.objects.select_for_update().get(board=board_model,row=row,col=col)
        except ObjectDoesNotExist:
            return False
        if cell.is_revealed:
            return
        cell.is_flagged = True
        cell.save()
    elif move =='unflag':
        try:
            cell = Cell.objects.select_for_update().get(board=board_model,row=row,col=col)
        except ObjectDoesNotExist:
            return False
        if cell.is_revealed:
            return
        cell.is_flagged = False
        cell.save()

    return {
        "status": "normal",
        "reveal_all": False,
    }
        
def update_players_status(board, status):
    # update players' status
    board.is_finished = True
    board.save()
    active_players = []
    players = Board_Participation.objects.filter(board=board, status='active')
    for player in players:
        if status == 'win':
            player.user.wins += 1
        player.user.games_played += 1
        player.status = status
        player.user.save()
        active_players.append(player) 
    Board_Participation.objects.bulk_update(active_players, ['status'])

@transaction.atomic 
def generate_cells(board_model):
    if board_model.is_generated:
        return
    board_model = Board.objects.select_for_update().get(pk=board_model.id)
    board = {}
    for i in range(0,30):
        board[i] = {}
        for j in range(0,16):
            board[i][j] = {
                'is_mine': False,
                'is_revealed': False,
                'is_flagged': False,
                'value': 0 
            }

    row = random.randint(0,29)
    col = random.randint(0,15)

    # place mines on cells
    mine_count = 0
    while mine_count < 99:
        cell_row = random.randint(0,29)
        cell_col = random.randint(0,15)
        if board[cell_row][cell_col]['is_mine']:
            continue
        # filter generated cells to only allow mines outside the 3x3 area of the first generated cell
        if (cell_row > (row+1) or cell_row < (row-1)) or (cell_col > (col+1) or cell_col < (col-1)):
            board[cell_row][cell_col]['is_mine'] = True 
            mine_count += 1
        
    mines = 0
    rows = 30
    cols = 16
 
    # check mines around a cell and place values
    for i in range(rows):
        for j in range(cols):
            mines = 0
            # increase/decrease indexes i and j through k and l
            for k in (-1,0,1):
                ik = i + k
                for l in (-1,0,1):
                    jl = j + l
                    if ik > 29 or ik < 0 or jl > 15 or jl < 0:
                        continue
                    # use data structure for mine checks
                    if board[ik][jl]['is_mine']:
                        mines+=1
                    # update value of jl
            board[i][j]['value'] = mines
    check_floodfills(row,col,board)
    # save board to database in one call instead of using .save numerous times
    cells = []
    for i in range(0,30):
        for j in range(0,16):
            cells.append(
                Cell(
                    board=board_model,
                    row=i,
                    col=j,
                    is_mine=board[i][j]['is_mine'],
                    value=board[i][j]['value'],
                    is_revealed=board[i][j]['is_revealed'],
                )
            )
    Cell.objects.bulk_create(cells)
    board_model.is_generated = True
    board_model.save()

# use recursion to to navigate floodfill
def check_floodfills(row,col,board):
    # base case
    if board[row][col]['is_revealed']:
        return 
    board[row][col]['is_revealed'] = True

    if board[row][col]['value'] > 0:
        return

    for i in (-1,0,1):
        i_row = row + i
        for j in (-1,0,1): 
            j_col = col + j
            if i_row < 0 or i_row > 29 or j_col < 0 or j_col > 15:
                continue
            if board[i_row][j_col]['is_mine']:
                continue
            if board[i_row][j_col]['value'] == 0:
                # repeat process for the identified empty node
                check_floodfills(i_row, j_col, board) 
            board[i_row][j_col]['is_revealed'] = True
    # returns after checking all nodes in the 3x3 area
    return

def check_participation(user):
    try:
        participation = Board_Participation.objects.get(user=user,has_left=False,board__is_finished=False)
        return participation
    except ObjectDoesNotExist:
        pass
    return False  

def clean_unused_rooms():
    time_limit = timezone.now() - timedelta(minutes=15)
    # retrieve users who have been inactive for more than 15 minutes in their rooms and considere them as users who have left their rooms
    stale_participants = Board_Participation.objects.filter(last_seen__lt=time_limit)
    stale_participants.update(has_left=True)
    rooms = []
    for participant in stale_participants:
        if participant.board.room not in rooms:
            rooms.append(participant.board.room)

    for room in rooms:
        stale_room = True
        for participant in Board_Participation.objects.filter(board__room=room):
            if participant.has_left == False:
                stale_room = False
        if stale_room:
            # delete room
            room.delete()

@transaction.atomic
def create_next_board(old_board, room):
    # update board to newly created one
    new_board = Board.objects.create(room_id=room)
    # transfer active players from old board to new board
    transferred_players = []
    # add last_seen attribute for the heartbeat(ping message) to the database, use that attribute to filter the to-be transferred players.
    # also use that attribute to alter participation mid-game (?)
    # transfer only players who have sent pings within the last 30 seconds
    # added has_left attribute to accomodate people who intentionally leaves the room
    current_time = timezone.now()
    time_limit = current_time - timedelta(seconds=30)
    
    for player in Board_Participation.objects.filter(board=old_board, has_left=False):
        # inactive players become spectators
        if player.last_seen >= time_limit:
            last_seen = current_time
            status = 'active'
        else:
            last_seen = player.last_seen
            status = 'spectator'
            
        transferred_players.append(
            Board_Participation(
                board=new_board,
                user_id = player.user_id,
                status = status,
                last_seen = last_seen,
                has_left=False
            )
        )
    # generate new cells for newly created board
    (generate_cells)(new_board)
    # creates new board_participation objects in bulk from the previous active and connected players
    Board_Participation.objects.bulk_create(transferred_players)
    return new_board