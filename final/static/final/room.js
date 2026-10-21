document.addEventListener('DOMContentLoaded', function() {
    console.log("room.js loaded");
    // retrieve room 
    const room_id = document.querySelector('#room_id').dataset.room;

    // create websocket connection
    const protocol = window.location.protocol === "https:" ? "wss://" : "ws://";
    const socket = new WebSocket(
        protocol + window.location.host + '/ws/room/'+ room_id + '/'
    );

    const heartbeat = setInterval(() => {
        if (socket.readyState === WebSocket.OPEN){
            socket.send(JSON.stringify({
                function: 'ping'
            }))
        }
    }, 30000) // 30 seconds
    
    // send a message later
    socket.onclose = function(e) {
        clearInterval(heartbeat)
    }

    // leave room logic
    document.querySelector('#leave-button').onclick = function() {
        // need room join
        window.location.pathname = `leave_room/`;
    };

    socket.onmessage = function(e) {
        // subject to change
        const data = JSON.parse(e.data);
        
        if (data.type == "board.render"){
            console.log("BOARD RENDER RECEIVED");
            if (data.move_status){
                document.querySelector('#transfer-view').style.display = 'block';
                document.querySelector('#transfer-view').style.visibility = 'visible';
                document.querySelector('#transfer-view').style.opacity = '1';
                if (data.move_status.status === 'win'){
                 // show a popup that says generating new board 
                    document.querySelector('#transfer-view').textContent  = "Howdy and Merry CHristmas! new board is on the way"
                }
                else if (data.move_status.status === 'lose'){
                    // show a popup that says generating new board 
                    document.querySelector('#transfer-view').textContent  = "Better Luck Next Tim, Folks! ur new board is on the way"
                }
            }
            render_board(data.cells)
            console.log(data.move_status)
            
        }   
        else if (data.type == "player.render"){
            render_player(data.participants)
        }
        else if (data.type == "board.new"){
            console.log("NEW BOARD RECEIVED");
            document.querySelector('#transfer-view').innerHTML = ""
            document.querySelector('#board-view').dataset.board = data.board_id
            initial_board(socket, data.cells) // to be adjusted
        }
    };
});


function initial_board(socket, cells) {
    // create board with cells from server
    console.log("clicked")
    document.querySelector('#board-view').innerHTML = "";
    for (let i = 0; i < 30; i++) {
        for (let j = 0; j < 16; j++) {
            const cell = document.createElement("div");
            cell.className = 'cell is_unrevealed';
            cell.id = `row_${i}col_${j}`;
            cell.dataset.row = i;
            cell.dataset.col = j;
            document.querySelector('#board-view').append(cell);

            // left click (reveal)
            cell.onclick = function(){

                let move = ""
                // retrieve purpose of click
                if (cell.classList.contains("is_unrevealed") && !cell.classList.contains("is_flagged") ){
                    move = 'reveal'
                }
                if (!move){
                    return;
                }
                socket.send(JSON.stringify({
                    'function': "board_update",
                    'board_id': document.querySelector('#board-view').dataset.board,
                    'move': move,
                    'row': this.dataset.row,
                    'col': this.dataset.col,
                }));
                return false;
            }
            // right click (flag/unflag)
            cell.oncontextmenu= function(e){
                // retrieve purpose of click
                console.log("clicked")
                e.preventDefault();
                let move = ""
                if (cell.classList.contains("is_flagged")){
                     move = "unflag";
                }
                else if (cell.classList.contains("is_unrevealed")){
                     move = "flag";
                }
                if (!move){
                    return;
                }
                socket.send(JSON.stringify({
                    'function': "board_update",
                    'board_id': document.querySelector('#board-view').dataset.board,
                    'move': move,
                    'row': this.dataset.row,
                    'col': this.dataset.col, 
                }));
                
                return false;
            }
        }
    }
    render_board(cells);
}

function render_board(cells) {
    // replace initial board with updated cells
    cells.cells.forEach(cell => {
        // identifies specific cell that corresponds with the json cell coordinates(row,col)
        const cell_html = document.querySelector(`#row_${cell.row}col_${cell.col}`)
        if (cell.value == 'is_mine'){
            cell_html.className = 'cell is_mine';
            cell_html.textContent = '🎃'
        }
        else if (cell.is_revealed){
            cell_html.className = 'cell is_revealed'
            cell_html.textContent = cell.value
        }
        else if (cell.is_flagged){
            cell_html.className = 'cell is_flagged'
            cell_html.textContent = '🕸️'
        }
        else{
            cell_html.className = 'cell is_unrevealed'
            cell_html.textContent = ''
        }
    })
}

function render_player(participants) {
    // clear player view for every update
    document.querySelector('#player-view').innerHTML = ""
    // fill player view with participants
    const player = document.createElement("p");
    player.className = "player";
    participants.players.forEach(participant => {
        if (participant.online){
            connection = 'Online'
        }
        else{
            connection = 'Away'
        }
        if (participant.status != 'spectator'){
            player.append(` ${participant.username} | wins: ${participant.wins} | ${connection}  🎃 `) 
        }
        else{
            player.append(`${participant.username} (${participant.status}) | ${connection} | wins: ${participant.wins} 🎃  `)
        }
    })
    document.querySelector('#player-view').append(player);
}
