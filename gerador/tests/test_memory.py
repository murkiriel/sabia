"""A memória da geração no log (sabia/memory.py): o RSS e o pico em cada etapa do build, e a memória liberada devolvida
ao sistema entre as etapas (malloc_trim), para o Brasil caber no executor do Actions (7,8 GB de RAM)."""
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from sabia import memory  # noqa: E402

STATUS = "Name:\tpython\nVmPeak:\t 9000000 kB\nVmHWM:\t 7487172 kB\nVmRSS:\t 5242880 kB\nThreads:\t1\n"


class UsageTest(unittest.TestCase):
    def test_rss_and_peak_in_gigabytes(self):
        with mock.patch.object(memory, "_status", return_value=STATUS):
            self.assertEqual("memória 5.0 GB, pico 7.1 GB", memory.usage())

    def test_without_proc_nothing(self):  # Windows, macOS
        with mock.patch.object(memory, "_status", return_value=None):
            self.assertEqual("", memory.usage())

    def test_the_real_one_on_linux(self):
        if not Path("/proc/self/status").exists():
            self.skipTest("sem /proc")
        self.assertRegex(memory.usage(), r"^memória \d+\.\d GB, pico \d+\.\d GB$")


class ReleaseTest(unittest.TestCase):
    def test_calls_malloc_trim(self):
        libc = mock.Mock()
        with mock.patch.object(memory, "_libc", return_value=libc):
            memory.release()
        libc.malloc_trim.assert_called_once_with(0)

    def test_without_glibc_nothing_breaks(self):
        with mock.patch.object(memory, "_libc", return_value=None):
            memory.release()


if __name__ == "__main__":
    unittest.main()
