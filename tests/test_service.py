import json
import threading
import unittest
import urllib.error
import urllib.request

from procurement_desk.service import make_server
from tests.support import PB, PIPE, needs_data

THREAD = {"thread_id": "T1", "date": "2026-10-01", "supplier": "Garnet Print & Paper", "category": "headsets",
          "quantity": 5, "round": 1, "our_last_counter": "", "supplier_message": "we can do ₹3,900 per headset."}


@needs_data
class ServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = make_server(PIPE, "127.0.0.1", 0)
        cls.base = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def call(self, path, payload=None, raw=None):
        data = raw if raw is not None else (json.dumps(payload).encode() if payload is not None else None)
        request = urllib.request.Request(self.base + path, data=data, headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            return error.code, json.loads(error.read())

    def test_health_reports_the_playbook_version(self):
        status, body = self.call("/healthz")
        self.assertEqual((status, body["status"], body["playbook_fingerprint"]), (200, "ok", PB.fingerprint))

    def test_decision_endpoint(self):
        status, body = self.call("/v1/decisions", THREAD)
        self.assertEqual((status, body["label"], body["fired_rule"]), (200, "COUNTER:COUNTER_OFFER:3500", "R5"))
        self.assertTrue(body["price_trace"])

    def test_batch_endpoint(self):
        status, body = self.call("/v1/decisions:batch", {"threads": [THREAD, {**THREAD, "thread_id": "T2", "quantity": 5000,
                                                                              "supplier_message": "we can do ₹3,400 per headset."}]})
        self.assertEqual((status, [r["label"] for r in body["results"]]),
                         (200, ["COUNTER:COUNTER_OFFER:3500", "ESCALATE:OVER_APPROVAL_LIMIT:"]))

    def test_bad_requests_get_a_400_not_a_crash(self):
        self.assertEqual(self.call("/v1/decisions", raw=b"{not json")[0], 400)
        self.assertEqual(self.call("/v1/decisions", {**THREAD, "quantity": 0})[0], 400)
        self.assertEqual(self.call("/v1/decisions", {k: v for k, v in THREAD.items() if k != "category"})[0], 400)
        self.assertEqual(self.call("/v1/decisions:batch", {"threads": []})[0], 400)
        self.assertEqual(self.call("/nope")[0], 404)


if __name__ == "__main__":
    unittest.main()
