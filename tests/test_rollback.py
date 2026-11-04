import unittest

from vlanmanager.core.rollback import RollbackError, run_with_rollback


class RollbackTest(unittest.TestCase):
    def setUp(self):
        self.calls = []

    def _apply(self):
        self.calls.append("apply")

    def _undo(self):
        self.calls.append("undo")

    def test_confirmed_keeps_change(self):
        self.assertTrue(run_with_rollback(self._apply, self._undo, lambda: True))
        self.assertEqual(self.calls, ["apply"])

    def test_timeout_runs_undo(self):
        self.assertFalse(run_with_rollback(self._apply, self._undo, lambda: False))
        self.assertEqual(self.calls, ["apply", "undo"])

    def test_apply_error_runs_undo_and_reraises(self):
        def bad():
            raise ValueError("boom")
        with self.assertRaises(ValueError):
            run_with_rollback(bad, self._undo, lambda: True)
        self.assertEqual(self.calls, ["undo"])

    def test_undo_failure_raises_rollback_error(self):
        def bad_undo():
            raise OSError("undo failed")
        with self.assertRaises(RollbackError):
            run_with_rollback(self._apply, bad_undo, lambda: False)

    def test_undo_failure_after_apply_error_chains_original(self):
        original = ValueError("boom")

        def bad():
            raise original

        def bad_undo():
            raise OSError("undo failed")
        with self.assertRaises(RollbackError) as ctx:
            run_with_rollback(bad, bad_undo, lambda: True)
        self.assertIs(ctx.exception.__cause__, original)


if __name__ == "__main__":
    unittest.main()
