import unittest
from unittest.mock import MagicMock

from collector import extract_log, send_log


class TestExtractLog(unittest.TestCase):
    def test_maps_tracee_event_to_backend_model(self):
        event = {
            "processId": 123,
            "threadId": 12.5,
            "parentProcessId": 1,
            "userId": 1000,
            "mountNamespace": 4_026_531_842,
            "eventId": 46,
            "argsNum": 2,
            "returnValue": 0,
            "sus": 1,
            "evil": None,
            "comm": "test",
        }

        result = extract_log(event)

        self.assertEqual(result["processid"], 123)
        self.assertEqual(result["threadId"], 12.5)
        self.assertEqual(result["mountNamespace"], 4_026_531_842)
        self.assertIsNone(result["evil"])
        self.assertNotIn("comm", result)

    def test_rejects_missing_required_fields(self):
        with self.assertRaisesRegex(ValueError, "processid"):
            extract_log({})

    def test_invokes_backend_send_log_with_one_model_object(self):
        hub = MagicMock()

        def invoke(_method, _arguments, on_invocation):
            on_invocation([MagicMock(error=None)])

        hub.invoke.side_effect = invoke
        record = {"processid": 123}

        send_log(hub, record)

        hub.invoke.assert_called_once()
        self.assertEqual(hub.invoke.call_args.args[0], "sendLog")
        self.assertEqual(hub.invoke.call_args.args[1], [record])


if __name__ == "__main__":
    unittest.main()
