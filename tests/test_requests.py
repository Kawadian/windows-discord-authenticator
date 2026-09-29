import base64
import io
import json
import unittest
from PIL import Image

from approval_agent.requests_server import validate


class RequestTests(unittest.TestCase):
    def test_request_limits_and_image_validation(self):
        data = {key: "test" for key in
                ("trigger", "computer", "user", "window", "process", "captured_at")}
        data["trigger"] = "ホットキー"
        stream = io.BytesIO()
        Image.new("RGB", (4, 4), "red").save(stream, format="JPEG")
        data["jpeg"] = base64.b64encode(stream.getvalue()).decode()
        clean, image = validate(json.dumps(data).encode())
        self.assertEqual(clean["trigger"], "ホットキー")
        self.assertEqual(image, stream.getvalue())
        data["jpeg"] = base64.b64encode(b"not a JPEG").decode()
        with self.assertRaises(ValueError):
            validate(json.dumps(data).encode())
