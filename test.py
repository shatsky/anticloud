#python -m unittest -v
import unittest
import tempfile
import pathlib
import os

FILES = {
    # only in old
    '2024-01-01_foo/DCIM/20220101_000000.txt': '20220101_000000',
    # same in old and new
    '2024-01-01_foo/DCIM/20230101_000000.txt': '20230101_000000',
    '2025-01-01_foo/DCIM/20230101_000000.txt': '20230101_000000',
    # different in old and new
    '2024-01-01_foo/DCIM/20240101_000000.txt': '20240101_000000',
    '2025-01-01_foo/DCIM/20240101_000000.txt': '20240101_000000foo',
    # only in new
    '2025-01-01_foo/DCIM/20250101_000000.txt': '20250101_000000',
}

class MyTestCase(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        print('tmpdir path:', self.tmpdir.name)
        tmpdir_path = pathlib.Path(self.tmpdir.name)
        self.tmpdir_path = tmpdir_path
        for file_ in FILES:
            dir_ = os.path.dirname(file_)
            os.makedirs(os.path.join(*([self.tmpdir.name]+dir_.split('/'))), exist_ok=True)
            basename = os.path.basename(file_)
            if basename:
                (tmpdir_path / file_).write_text(FILES[file_])
        #import time
        #time.sleep(1)
        #pathlib.Path.touch(tmpdir_path/'2024-01-01_foo'/'DCIM'/'20230101_000000.txt')

    def tearDown(self):
        self.tmpdir.cleanup()

    def test(self):
        old = self.tmpdir_path / '2024-01-01_foo'
        new = self.tmpdir_path / '2025-01-01_foo'
        acc = self.tmpdir_path / 'accumulator'
        #os.environ['ANTICLOUD_READONLY'] = '0'
        exit_status = os.system("python3 anticloud-auto.py {0}".format(self.tmpdir_path))
        input('press to cont')
        assert exit_status == 0
        exit_status = os.system("python3 anticloud-auto.py {0}".format(self.tmpdir_path))
        assert exit_status == 0
        #assert os.path.exists(old / 'DCIM/20220101_000000.txt')
        assert (old / 'DCIM/20220101_000000.txt').read_text() == '20220101_000000'
        #assert not os.path.exists(new / 'DCIM/20220101_000000.txt')
        assert os.path.samefile(old / 'DCIM/20230101_000000.txt', new / 'DCIM/20230101_000000.txt')
        assert (old / 'DCIM/20230101_000000.txt').read_text() == '20230101_000000'
        assert not os.path.samefile(old / 'DCIM/20240101_000000.txt', new / 'DCIM/20240101_000000.txt')
        assert (old / 'DCIM/20240101_000000.txt').read_text() == '20240101_000000'
        assert (new / 'DCIM/20240101_000000.txt').read_text() == '20240101_000000foo'
        #assert not os.path.exists(old / 'DCIM/20250101_000000.txt')
        #assert os.path.exists(new / 'DCIM/20250101_000000.txt')
        assert (new / 'DCIM/20250101_000000.txt').read_text() == '20250101_000000'
        assert os.path.samefile(old / 'DCIM/20220101_000000.txt', acc / '20220101_000000.txt')
        assert os.path.samefile(old / 'DCIM/20230101_000000.txt', acc / '20230101_000000.txt')
        assert os.path.samefile(old / 'DCIM/20240101_000000.txt', acc / '20240101_000000.txt')
        assert os.path.samefile(new / 'DCIM/20250101_000000.txt', acc / '20250101_000000.txt')
