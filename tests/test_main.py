"""Защита от второго экземпляра."""

import ctypes
import unittest
import uuid

import main


class SingleInstanceTest(unittest.TestCase):
    def test_second_instance_is_refused(self):
        name = f"Local\\LyusyaTest-{uuid.uuid4()}"  # своё имя, чтобы не мешать запущенной Люсе
        first = main.acquire_single_instance(name)
        self.assertIsNotNone(first)
        self.addCleanup(ctypes.windll.kernel32.CloseHandle, ctypes.c_void_p(first))
        self.assertIsNone(main.acquire_single_instance(name))

    def test_free_again_after_release(self):
        name = f"Local\\LyusyaTest-{uuid.uuid4()}"
        first = main.acquire_single_instance(name)
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(first))
        again = main.acquire_single_instance(name)
        self.assertIsNotNone(again)
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(again))


if __name__ == "__main__":
    unittest.main()
