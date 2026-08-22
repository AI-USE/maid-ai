import os
import json
import time
import random
import string
from flask import Flask, render_template, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'yandere_horror_escape_secret_key_2025')
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='gevent', max_http_buffer_size=5 * 1024 * 1024)

def load_json(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        return json.load(f)

QUESTIONS = load_json('questions.json')
TITLES = load_json('titles.json')

# Total game duration in seconds
GAME_DURATION_SECONDS = 180

def generate_escape_code():
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

# Room state storage (10 rooms)
rooms_state = {}

def init_room(room_id):
    return {
        "room_id": str(room_id),
        "status": "waiting",  # waiting, countdown, playing, finished
        "start_time": None,   # Unix timestamp when timer started
        "duration": GAME_DURATION_SECONDS,
        "escape_code": generate_escape_code(),
        "camera_enabled": False,  # Remote camera streaming status
        "clients": {}  # sid: {device_name, current_q, continues, status, clear_time, title, comment}
    }

for i in range(1, 11):
    r_id = f"Room_{i}"
    rooms_state[r_id] = init_room(r_id)

def compute_title(status, current_q, continues):
    if status == 'cleared':
        for t in sorted(TITLES['clear'], key=lambda x: x['max_continues']):
            if continues <= t['max_continues']:
                return t['title'], t['comment']
        last = TITLES['clear'][-1]
        return last['title'], last['comment']
    else:  # gameover / failed
        for t in sorted(TITLES['gameover'], key=lambda x: x['min_reached'], reverse=True):
            if current_q >= t['min_reached']:
                return t['title'], t['comment']
        last = TITLES['gameover'][-1]
        return last['title'], last['comment']

def sanitize_questions_for_client(questions):
    client_q = []
    for q in questions:
        client_q.append({
            "id": q["id"],
            "question": q["question"],
            "options": q["options"],
            "commentary": q["commentary"],
            "maid_scold": q["maid_scold"]
        })
    return client_q

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/admin')
def admin():
    return render_template('admin.html')

@app.route('/builder')
def builder():
    return render_template('builder.html')

@app.route('/api/questions')
def get_questions():
    return jsonify(sanitize_questions_for_client(QUESTIONS))

@app.route('/api/questions/save', methods=['POST'])
def save_questions():
    global QUESTIONS
    try:
        new_questions = request.json
        if not isinstance(new_questions, list):
            return jsonify({"success": False, "message": "Data must be a list of questions"}), 400

        # Validate structure
        for idx, q in enumerate(new_questions, start=1):
            q["id"] = idx
            if "question" not in q or "options" not in q or "answer" not in q:
                return jsonify({"success": False, "message": f"Question {idx} is missing required fields"}), 400

        with open('questions.json', 'w', encoding='utf-8') as f:
            json.dump(new_questions, f, ensure_ascii=False, indent=2)

        QUESTIONS = new_questions
        return jsonify({"success": True, "message": "Questions saved successfully!", "count": len(new_questions)})
    except Exception as e:
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/api/titles')
def get_titles():
    return jsonify(TITLES)

# --- SocketIO Handlers ---

@socketio.on('connect')
def handle_connect():
    emit('admin_state_update', rooms_state)

@socketio.on('join_room_req')
def handle_join_room(data):
    room_id = data.get('room_id')
    device_name = data.get('device_name', f"Device_{request.sid[:4]}")

    if not room_id or room_id not in rooms_state:
        emit('error_msg', {'message': 'Invalid room ID'})
        return

    join_room(room_id)
    room = rooms_state[room_id]

    room['clients'][request.sid] = {
        "sid": request.sid,
        "device_name": device_name,
        "current_q": data.get('current_q', 1),
        "continues": data.get('continues', 0),
        "status": data.get('status', room['status']),
        "clear_time": data.get('clear_time', None),
        "title": data.get('title', ''),
        "comment": data.get('comment', '')
    }

    emit('sync_response', {
        "room_id": room_id,
        "room_status": room['status'],
        "start_time": room['start_time'],
        "duration": room['duration'],
        "escape_code": room['escape_code'],
        "camera_enabled": room['camera_enabled'],
        "client_state": room['clients'][request.sid]
    })

    socketio.emit('admin_state_update', rooms_state)

@socketio.on('sync_request')
def handle_sync_request(data):
    room_id = data.get('room_id')
    if not room_id or room_id not in rooms_state:
        emit('error_msg', {'message': 'Invalid room ID'})
        return

    join_room(room_id)
    room = rooms_state[room_id]

    client_info = room['clients'].get(request.sid, {
        "sid": request.sid,
        "device_name": data.get('device_name', f"Device_{request.sid[:4]}"),
        "current_q": data.get('current_q', 1),
        "continues": data.get('continues', 0),
        "status": 'playing' if room['status'] == 'playing' else room['status'],
        "clear_time": None,
        "title": '',
        "comment": ''
    })

    if 'current_q' in data:
        client_info['current_q'] = data['current_q']
    if 'continues' in data:
        client_info['continues'] = data['continues']
    if 'device_name' in data:
        client_info['device_name'] = data['device_name']

    room['clients'][request.sid] = client_info

    emit('sync_response', {
        "room_id": room_id,
        "room_status": room['status'],
        "start_time": room['start_time'],
        "duration": room['duration'],
        "escape_code": room['escape_code'],
        "camera_enabled": room['camera_enabled'],
        "client_state": client_info
    })

    socketio.emit('admin_state_update', rooms_state)

@socketio.on('client_update')
def handle_client_update(data):
    room_id = data.get('room_id')
    if not room_id or room_id not in rooms_state:
        return

    room = rooms_state[room_id]
    if request.sid in room['clients']:
        c = room['clients'][request.sid]
        c['current_q'] = data.get('current_q', c['current_q'])
        c['continues'] = data.get('continues', c['continues'])
        c['status'] = data.get('status', c['status'])

        if c['status'] == 'cleared' or c['status'] == 'gameover':
            title, comment = compute_title(c['status'], c['current_q'], c['continues'])
            c['title'] = title
            c['comment'] = comment

        socketio.emit('admin_state_update', rooms_state)

@socketio.on('submit_answer')
def handle_submit_answer(data):
    room_id = data.get('room_id')
    question_id = data.get('question_id')
    selected_option = data.get('selected_option')

    if not room_id or room_id not in rooms_state:
        return

    q_data = next((q for q in QUESTIONS if q['id'] == question_id), None)
    if not q_data:
        return

    is_correct = (q_data['answer'] == selected_option)

    emit('answer_result', {
        "question_id": question_id,
        "is_correct": is_correct,
        "correct_answer": q_data['answer'],
        "commentary": q_data['commentary'],
        "maid_scold": q_data['maid_scold']
    })

# --- Remote Camera Streaming Relay Handlers ---

@socketio.on('camera_frame')
def handle_camera_frame(data):
    room_id = data.get('room_id')
    frame_data = data.get('frame')
    if room_id in rooms_state and rooms_state[room_id]['camera_enabled']:
        socketio.emit('admin_camera_stream', {
            "room_id": room_id,
            "frame": frame_data
        })

@socketio.on('admin_toggle_camera')
def handle_admin_toggle_camera(data):
    room_id = data.get('room_id')
    enabled = data.get('enabled', False)

    if room_id == 'ALL':
        for r_id, room in rooms_state.items():
            room['camera_enabled'] = enabled
            socketio.emit('toggle_camera', {
                "room_id": r_id,
                "enabled": enabled
            }, room=r_id)
    elif room_id in rooms_state:
        rooms_state[room_id]['camera_enabled'] = enabled
        socketio.emit('toggle_camera', {
            "room_id": room_id,
            "enabled": enabled
        }, room=room_id)

    socketio.emit('admin_state_update', rooms_state)

# --- Admin Handlers ---

@socketio.on('admin_start_room')
def handle_admin_start_room(data):
    room_id = data.get('room_id')
    if room_id in rooms_state:
        room = rooms_state[room_id]
        room['status'] = 'playing'
        room['start_time'] = time.time()
        for c in room['clients'].values():
            c['status'] = 'playing'

        socketio.emit('game_started', {
            "room_id": room_id,
            "start_time": room['start_time'],
            "duration": room['duration']
        }, room=room_id)

        socketio.emit('admin_state_update', rooms_state)

@socketio.on('admin_reset_room')
def handle_admin_reset_room(data):
    room_id = data.get('room_id')
    if room_id in rooms_state:
        rooms_state[room_id] = init_room(room_id)
        socketio.emit('room_reset', {
            "room_id": room_id
        }, room=room_id)
        socketio.emit('admin_state_update', rooms_state)

@socketio.on('admin_start_all')
def handle_admin_start_all():
    now = time.time()
    for room_id, room in rooms_state.items():
        room['status'] = 'playing'
        room['start_time'] = now
        for c in room['clients'].values():
            c['status'] = 'playing'
        socketio.emit('game_started', {
            "room_id": room_id,
            "start_time": now,
            "duration": room['duration']
        }, room=room_id)
    socketio.emit('admin_state_update', rooms_state)

@socketio.on('admin_reset_all')
def handle_admin_reset_all():
    for room_id in rooms_state.keys():
        rooms_state[room_id] = init_room(room_id)
        socketio.emit('room_reset', {
            "room_id": room_id
        }, room=room_id)
    socketio.emit('admin_state_update', rooms_state)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f"Starting Yandere Horror Server on http://0.0.0.0:{port}")
    socketio.run(app, host='0.0.0.0', port=port, debug=True)
