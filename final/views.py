# Create your views here.
# chat/views.py
from django.shortcuts import render
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect
from django.shortcuts import render
from django.urls import reverse
from django.db import IntegrityError, transaction
from django.db.models import Count, Q
from django.core.exceptions import ObjectDoesNotExist
from django.core.paginator import Paginator
from asgiref.sync import async_to_sync
import channels.layers
from django.utils import timezone
from django import forms

from .helpers import check_participation, clean_unused_rooms, generate_cells
from .models import User, Board, Cell, Board_Participation, Room

class room_form(forms.Form):
    room_name = forms.CharField(max_length=50)

class confirm_room_form(forms.Form):
    source = forms.ChoiceField(
        choices=[
            ("join_room", "Join Room"),
            ("create_room", "Create Room"),
        ]
    )
    room_id = forms.IntegerField(required=False)
    room_name = forms.CharField(
        max_length=50,
        required=False,
    )

def index(request):
    clean_unused_rooms()
    rooms = Room.objects.annotate(
    player_count=Count(
            "boards__participations",
            filter=Q(
                boards__is_finished=False,
                boards__participations__has_left=False,
            ),
        )
    )
    paginator = Paginator(rooms, 10) # 10 posts per page
    page_number = request.GET.get('page')
    page = paginator.get_page(page_number) # retrieve page 1

    return render(request, "final/index.html", {
        'page': page,
        "form": room_form()
    })

# create room
@login_required
def create_room(request):
    participation = check_participation(request.user)

    if request.method != "POST":
        return render(request, "final/create_room.html", {
            "form": room_form()
        })

    form = room_form(request.POST)

    if not form.is_valid():
        return render(request, "final/create_room.html", {
            "form": form
        })

    room_name = form.cleaned_data["room_name"]

    # Ask for confirmation if the user is already in a room.
    if participation:
        return render(request, "final/confirmation.html", {
            "active_room": participation.board.room.id,
            "role": participation.status,
            "url": "create_room",
            "room_name": room_name,
        })

    # Otherwise, create the room immediately.
    try:
        room = Room.objects.create(room_name=room_name)
        board = Board.objects.create(room=room)
        generate_cells(board)

        Board_Participation.objects.create(
            user=request.user,
            last_seen=timezone.now(),
            board=board,
            has_left=False,
            status="active",
        )

        return HttpResponseRedirect(reverse("room", args=[room.id]))

    except IntegrityError:
        return HttpResponse("Unable to Create Room.")
      
@login_required 
def room(request, room_id):
    # retrieve desired room and current board
    try:
        room = Room.objects.get(pk=room_id)
        board = Board.objects.get(room=room, is_finished=False)
    except ObjectDoesNotExist:
        # if room has been deleted
        return HttpResponseRedirect(reverse('index'))
    
    participation = check_participation(request.user)
    if participation:
        if participation.board.room != room: 
            return render(request, "final/confirmation.html", {  
                    'active_room': participation.board.room.id,
                    'role': participation.status,
                    'url': 'join_room',
                    'room_id': room_id,
                    'room_name': participation.board.room.room_name
            })    
    
    # assess if rejoiners are allowed
    try:
        current_participation = Board_Participation.objects.get(user=request.user, board=board)
        # implement new game design
        if current_participation.has_left:
            current_participation.has_left = False
        current_participation.last_seen = timezone.now()
        current_participation.save()
         # update player list to previous group
        channel_layer = channels.layers.get_channel_layer()
        # notifies previous room that user has left
        async_to_sync(channel_layer.group_send)( 
            f"room_{current_participation.board.room.id}",
            {
                "type": "player.render", "participants": current_participation.board.serialize_participants()
            }
        )
        
    except ObjectDoesNotExist:
        # new players
            try:
                if board.is_generated:
                    new_participation = Board_Participation.objects.create(user=request.user,last_seen=timezone.now(), board=board,has_left=False,status='spectator')
                else:
                    new_participation = Board_Participation.objects.create(user=request.user,last_seen=timezone.now(), board=board,has_left=False,status='active')
                new_participation.save()
                # update player list to previous group
                channel_layer = channels.layers.get_channel_layer()
                # notifies previous room that user has left
                async_to_sync(channel_layer.group_send)(
                    f"room_{new_participation.board.room.id}",
                    {
                        "type": "player.render", "participants": new_participation.board.serialize_participants()
                    }
                )
            except IntegrityError:
                return HttpResponse('Joining Room Error')
        
    # finally render room
    return render(request, "final/room.html", {
        "room_id": room.id,
        "board_id": board.id
    })

@login_required
def confirm_room(request):
    if request.method != "POST":
        return HttpResponseRedirect(reverse("index"))

    form = confirm_room_form(request.POST)

    if not form.is_valid():
        return HttpResponseRedirect(reverse("index"))

    source = form.cleaned_data["source"]
    room_id = form.cleaned_data["room_id"]
    room_name = form.cleaned_data["room_name"]

    # Validate the destination before leaving the current room.
    if source == "join_room":
        try:
            room = Room.objects.get(pk=room_id)
            Board.objects.get(room=room, is_finished=False)
        except ObjectDoesNotExist:
            return HttpResponseRedirect(reverse("index"))

    participation = check_participation(request.user)
    if participation:
        old_board = participation.board
    else:
        old_board = None
     
    try:
        with transaction.atomic():
            if participation:
                participation.has_left = True
                participation.save(update_fields=["has_left"])

            if source == "create_room":
                room = Room.objects.create(room_name=room_name)
                board = Board.objects.create(room=room)
                generate_cells(board)

                Board_Participation.objects.create(
                    user=request.user,
                    last_seen=timezone.now(),
                    board=board,
                    has_left=False,
                    status="active",
                )

    except IntegrityError:
        return HttpResponse("Unable to complete room change.")

    # Notify the old room after the database transaction succeeds.
    if old_board:
        channel_layer = channels.layers.get_channel_layer()
        async_to_sync(channel_layer.group_send)(
            f"room_{old_board.room.id}",
            {
                "type": "player.render",
                "participants": old_board.serialize_participants(),
            },
        )

    if source == "join_room":
        return HttpResponseRedirect(reverse("room", args=[room_id]))
    return HttpResponseRedirect(reverse("room", args=[room.id]))
@login_required 
def leave_room(request):
    participation = check_participation(request.user)
    if participation:
        participation.has_left = True
        participation.save()
        # update player list to previous group
        channel_layer = channels.layers.get_channel_layer()
        # notifies previous room that user has left
        async_to_sync(channel_layer.group_send)(
            f"room_{participation.board.room.id}",
            {
                "type": "player.render", "participants": participation.board.serialize_participants()
            }
        )
    return HttpResponseRedirect(reverse('index'))
        
def login_view(request):
    if request.method == "POST":

        # Attempt to sign user in
        username = request.POST["username"]
        password = request.POST["password"]
        user = authenticate(request, username=username, password=password)
  
        # Check if authentication successful
        if user is not None:
            login(request, user)
            return HttpResponseRedirect(reverse("index"))
        else:
            return render(request, "final/login.html", {
                "message": "Invalid username and/or password."
            })
    else:
        return render(request, "final/login.html")

def logout_view(request):
    # force to end websocket connection if one exist
    participation = check_participation(request.user)
    if participation:
        participation.has_left = True
        participation.save()
    logout(request)
    return HttpResponseRedirect(reverse("index"))

def register(request):
    if request.method == "POST":
        username = request.POST["username"]
        email = request.POST["email"]

        # Ensure password matches confirmation
        password = request.POST["password"]
        confirmation = request.POST["confirmation"]
        if password != confirmation:
            return render(request, "final/register.html", {
                "message": "Passwords must match."
            })

        # Attempt to create new user
        try:
            user = User.objects.create_user(username, email, password)
            user.save()
        except IntegrityError:
            return render(request, "final/register.html", {
                "message": "Username already taken."
            })
        login(request, user)
        return HttpResponseRedirect(reverse("index"))
    else:
        return render(request, "final/register.html")