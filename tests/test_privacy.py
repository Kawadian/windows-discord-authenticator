import threading
import unittest
from dataclasses import replace
from approval_agent.privacy import CaptureGate, Privacy


class Frame:
    closed = False
    def close(self):
        self.closed = True


class Camera:
    def __init__(self):
        self.frames = []
        self.closed = False
    def grab(self):
        frame = Frame()
        self.frames.append(frame)
        return frame
    def close(self):
        self.closed = True


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.cameras = []
        self.metadata_calls = []
        def factory():
            camera = Camera()
            self.cameras.append(camera)
            return camera
        def metadata(privacy):
            self.metadata_calls.append(privacy)
            return dict(computer='private-pc', user='private-user', window='private-title',
                        process='private-process', captured_at='private-time')
        self.gate = CaptureGate(factory, metadata, lambda image: 'encoded-image')

    def test_defaults_and_manual_request_never_construct_camera(self):
        self.gate.sample()
        sent = []
        self.gate.deliver('ホットキー', True, sent.append)
        self.assertEqual(self.cameras, [])
        self.assertIsNone(sent[0]['jpeg'])
        for key in ('computer', 'user', 'window', 'process', 'captured_at'):
            self.assertEqual(sent[0][key], '非共有')

    def test_disable_disposes_frame_and_backend_and_prevents_future_capture(self):
        self.gate.apply(Privacy(screenshots=True))
        self.gate.sample()
        camera = self.cameras[0]
        frame = camera.frames[0]
        self.gate.apply(Privacy())
        self.assertTrue(frame.closed)
        self.assertTrue(camera.closed)
        self.assertIsNone(self.gate.latest)
        for _ in range(10):
            self.gate.sample()
            self.gate.deliver('ホットキー', True, lambda data: self.assertIsNone(data['jpeg']))
        self.assertEqual(len(camera.frames), 1)
        self.assertEqual(len(self.cameras), 1)

    def test_reenable_uses_new_camera_and_never_stale_image(self):
        self.gate.apply(Privacy(screenshots=True))
        self.gate.sample()
        self.gate.apply(Privacy())
        self.gate.apply(Privacy(screenshots=True))
        self.assertIsNone(self.gate.latest)
        self.gate.sample()
        self.assertEqual(len(self.cameras), 2)

    def test_pending_request_obeys_new_switches(self):
        self.gate.apply(Privacy(screenshots=True, computer=True, automatic=True))
        self.gate.sample()
        self.gate.apply(Privacy(user=True))
        sent = []
        self.gate.deliver('UAC 自動検知', False, sent.append)
        self.assertFalse(sent)
        self.gate.deliver('ホットキー', False, sent.append)
        self.assertEqual(sent[0]['user'], 'private-user')
        self.assertEqual(sent[0]['computer'], '非共有')
        self.assertIsNone(sent[0]['jpeg'])

    def test_apply_waits_for_inflight_capture_then_closes_it(self):
        entered, release, applied = threading.Event(), threading.Event(), threading.Event()
        self.gate.apply(Privacy(screenshots=True))
        self.gate.sample()
        camera = self.cameras[0]
        normal_grab = camera.grab
        def blocking_grab():
            entered.set()
            self.assertTrue(release.wait(3))
            return normal_grab()
        camera.grab = blocking_grab
        capture = threading.Thread(target=self.gate.sample)
        capture.start()
        self.assertTrue(entered.wait(2))
        def disable():
            self.gate.apply(Privacy())
            applied.set()
        change = threading.Thread(target=disable)
        change.start()
        self.assertFalse(applied.wait(.05))
        release.set()
        capture.join(3)
        change.join(3)
        self.assertTrue(applied.is_set())
        self.assertTrue(camera.closed)
        self.assertTrue(all(frame.closed for frame in camera.frames))
        self.gate.sample()
        self.assertEqual(len(camera.frames), 2)

    def test_shutdown_blocks_even_manual_capture(self):
        self.gate.apply(Privacy(screenshots=True))
        self.gate.close()
        self.gate.sample()
        self.gate.deliver('ホットキー', True, lambda payload: self.fail('Sent after exit'))
        self.assertFalse(self.cameras)

    def test_bad_preferences_fail_closed(self):
        self.assertEqual(Privacy.parse({'screenshots': 'true', 'user': 1}), Privacy())


if __name__ == '__main__':
    unittest.main()
