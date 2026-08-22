import unittest
import json
import os
from app import app, socketio, rooms_state, QUESTIONS, TITLES

class YandereAppTestCase(unittest.TestCase):
    def setUp(self):
        self.app = app.test_client()
        self.app.testing = True

    def test_json_files_structure(self):
        self.assertEqual(len(QUESTIONS), 10)
        for q in QUESTIONS:
            self.assertIn("id", q)
            self.assertIn("question", q)
            self.assertIn("options", q)
            self.assertIn("answer", q)
            self.assertIn("commentary", q)
            self.assertIn("maid_scold", q)

        self.assertIn("clear", TITLES)
        self.assertIn("gameover", TITLES)

    def test_api_routes(self):
        res_q = self.app.get('/api/questions')
        self.assertEqual(res_q.status_code, 200)
        q_data = json.loads(res_q.data)
        self.assertEqual(len(q_data), 10)

        res_t = self.app.get('/api/titles')
        self.assertEqual(res_t.status_code, 200)

    def test_admin_route(self):
        res = self.app.get('/admin')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'MATRIX MONITOR', res.data)

    def test_index_route(self):
        res = self.app.get('/')
        self.assertEqual(res.status_code, 200)
        self.assertIn(b'Zen Maru Gothic', res.data)

    def test_socketio_connection(self):
        client = socketio.test_client(app)
        self.assertTrue(client.is_connected())

        client.emit('join_room_req', {
            'room_id': 'Room_1',
            'device_name': 'TestUser',
            'current_q': 1,
            'continues': 0,
            'status': 'waiting'
        })
        received = client.get_received()
        self.assertTrue(any(r['name'] == 'sync_response' for r in received))

if __name__ == '__main__':
    unittest.main()
