function getURLParameter(name) {
  return decodeURIComponent((new RegExp('[?|&]' + name + '=' + '([^&;]+?)(&|#|;|$)').exec(location.search) || [null, ''])[1].replace(/\+/g, '%20')) || null;
}

window.onload = function () {
    var main_container = document.querySelector('#main-container');
    var disconnected_modal_container = document.querySelector('#disconnected-modal-container');
    
    var stream_schedule = document.querySelector('#stream-schedule');
    var stream_buffers = document.querySelector('#stream-buffers');
    var stream_log = document.querySelector('#stream-log');
    var stream_state = document.querySelector('#stream-state');
    
    let buffer_tds = {};
    
    var act_restart = document.querySelector('#stream-act-restart');
    var act_stop = document.querySelector('#stream-act-stop');
    var act_start = document.querySelector('#stream-act-start');

    var hostname = getURLParameter('hostname');
    if (!hostname) var hostname = window.location.hostname;
    
    var title = getURLParameter('title');
    if (!title) var title = hostname;
    document.querySelector('#server-title').innerHTML = title;
    
    var port = parseFloat(getURLParameter('port'));
    if (!port) var port = 8081

    ws = new WebSocket(`ws://${hostname}:${port}`);
    
    ws.onopen = (event) => {
        main_container.className = '';
        disconnected_modal_container.className = 'hidden';
        
        window.setTimeout(() => {
            console.log('blah');
            disconnected_modal_container.className = 'hidden disabled';
        }, 1000);
    };

    ws.onmessage = (event) => {
        var do_log = true;
        var type = event.data.substr(0, event.data.indexOf(' '));
        var data = event.data.substr(event.data.indexOf(' ') + 1);
        
        console.log(type, data);
        
        if (type == 'state') {
            stream_state.innerHTML = data;
            stream_state.className = `stream-state-${data}`;
            
            if (data == 'stopped') {
                act_restart.disabled = true;
                act_stop.disabled = true;
                act_start.disabled = false;
            } else if (data == 'streaming') {
                act_restart.disabled = false;
                act_stop.disabled = false;
                act_start.disabled = true;
            }
        } else if (type == 'schedule') {
            do_log = false;

            row = document.createElement('tr');
            
            event = document.createElement('td');
            event.innerHTML = data.substr(0, data.indexOf(' ')).slice(7);
            row.appendChild(event);
            
            time = document.createElement('td');
            time.innerHTML = data.substr(data.indexOf(' ') + 1);
            row.appendChild(time);
            
            stream_schedule.appendChild(row);
        } else if (type == 'netsend_buffer') {
            do_log = false;
            
            filename = data.substr(data.indexOf(' ') + 1);
            
            if (buffer_tds[filename]) {
                buffer_tds[filename].innerHTML = data.substr(0, data.indexOf(' '));
            } else {
                row = document.createElement('tr');
                
                blah = document.createElement('td');
                blah.innerHTML = `<small>${filename}</small>`;
                row.appendChild(blah);
                
                size = document.createElement('td');
                size.innerHTML = data.substr(0, data.indexOf(' '));
                row.appendChild(size);
                buffer_tds[filename] = size;
                
                stream_buffers.appendChild(row);
            }
        }
                
        if (do_log) {
            var date = new Date();
            
            row = document.createElement('tr');
            
            time = document.createElement('td');
            time.innerHTML = `${('0' + date.getHours()).slice(-2)}:${('0' + date.getMinutes()).slice(-2)}:${('0' + date.getSeconds()).slice(-2)}`;
            row.appendChild(time);
            
            entry = document.createElement('td');
            entry.innerHTML = event.data;
            row.appendChild(entry);
            
            stream_log.appendChild(row);
        }
    }
    
    document.querySelectorAll('.stream-act').forEach((button) => {
        button.onclick = (event) => {
            ws.send(event.target.dataset.act);
        }
    });
}
