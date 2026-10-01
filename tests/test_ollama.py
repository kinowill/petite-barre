import json
import unittest
from unittest.mock import patch

import app


class Response:
    def __init__(self, body, status=200):
        self.body = body
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self, _size=None):
        return self.body

    def __iter__(self):
        return iter(self.body.splitlines(keepends=True))


class Connection:
    def __init__(self, response):
        self.response = response
        self.requests = []
        self.sock = None

    def request(self, *args):
        self.requests.append(args)

    def getresponse(self):
        return self.response

    def close(self):
        pass

    def connect(self):
        pass


class OllamaTests(unittest.TestCase):
    def test_lists_installed_models(self):
        body = json.dumps({"models": [{"name": "z:latest"}, {"name": "a:latest"}]}).encode()
        connection = Connection(Response(body))
        with patch.object(app.http.client, "HTTPConnection", return_value=connection):
            self.assertEqual(app.list_ollama_models(), ["a:latest", "z:latest"])
        self.assertEqual(connection.requests[0], ("GET", "/api/tags"))

    def test_chat_uses_selected_model(self):
        body = b'{"message":{"content":"bonjour"},"done":false}\n{"done":true}\n'
        connection = Connection(Response(body))
        with patch.object(app.http.client, "HTTPConnection", return_value=connection):
            chunks = list(app.stream_ollama([{"role": "user", "content": "salut"}], "another:model"))
        self.assertEqual(chunks, ["bonjour"])
        method, path, payload, headers = connection.requests[0]
        self.assertEqual((method, path, headers), ("POST", "/api/chat", {"Content-Type": "application/json"}))
        self.assertEqual(json.loads(payload)["model"], "another:model")

    def test_invalid_model_list_is_reported(self):
        connection = Connection(Response(b'{"models":{}}'))
        with patch.object(app.http.client, "HTTPConnection", return_value=connection), self.assertRaisesRegex(TypeError, "invalide"):
            app.list_ollama_models()


if __name__ == "__main__":
    unittest.main()
