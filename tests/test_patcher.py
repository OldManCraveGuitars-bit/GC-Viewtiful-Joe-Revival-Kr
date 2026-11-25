"""SPDX-License-Identifier: MIT
Real xdelta round trips and input/output preservation checks using small fixtures.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'patcher'))
import patcher


@unittest.skipUnless(os.name == 'nt', 'The bundled decoder is a Windows executable')
class PatcherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work_parent = REPO.parent / 'test-work'
        cls.work_parent.mkdir(exist_ok=True)
        cls.temporary = tempfile.TemporaryDirectory(prefix='patcher-', dir=cls.work_parent)
        cls.root = Path(cls.temporary.name).resolve()
        assert cls.root.is_relative_to(cls.work_parent.resolve())
        cls.source = cls.root / '일본판 원본.iso'
        cls.target = cls.root / 'fixture-target.bin'
        data = b'GVFJ08' + bytes(range(256)) * 4096
        cls.source.write_bytes(data)
        result = bytearray(data * 8)
        result[160:180] = b'Korean patch fixture'
        cls.expected = bytes(result)
        cls.target.write_bytes(cls.expected)
        cls.resources = cls.root / 'resources'
        cls.resources.mkdir()
        decoder = REPO / 'patcher/resources/xdelta3.exe'
        shutil.copy2(decoder, cls.resources / 'xdelta3.exe')
        delta = cls.resources / 'patch.xdelta'
        command = [str(decoder), '-e', '-f', '-s', str(cls.source), str(cls.target), str(delta)]
        proc = subprocess.run(command, capture_output=True)
        if proc.returncode:
            raise AssertionError(proc.stderr.decode('utf-8', 'replace'))
        (cls.resources / 'title.xml').write_text('<app><name>뷰티풀죠 리바이벌</name><coder>Capcom</coder><short_description>한국어 패치</short_description></app>', encoding='utf-8')
        entry = lambda p: dict(name=p.name, size=p.stat().st_size, sha256=patcher.digest(p))
        cls.manifest = dict(schema=1, version=patcher.VERSION, game_id='GVFJ08',
                            source=dict(size=len(data), sha256=hashlib.sha256(data).hexdigest()),
                            target=dict(size=len(cls.expected), sha256=hashlib.sha256(cls.expected).hexdigest()),
                            patch=entry(delta), decoder=entry(cls.resources / 'xdelta3.exe'),
                            sidecar=entry(cls.resources / 'title.xml'))
        (cls.resources / 'manifest.json').write_text(json.dumps(cls.manifest), encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        assert cls.root.is_relative_to(cls.work_parent.resolve())
        cls.temporary.cleanup()

    def setUp(self):
        self.folder = self.root / self._testMethodName
        self.folder.mkdir()

    def run_patch(self, output=None, **kwargs):
        return patcher.apply_patch(self.source, output, resources=self.resources, **kwargs)

    def assert_no_partial(self):
        self.assertFalse(list(self.folder.glob('.vjkr-*.partial')))

    def test_wrong_manifest_version_rejected(self):
        resources = self.folder / 'resources'
        shutil.copytree(self.resources, resources)
        manifest = json.loads((resources / 'manifest.json').read_text('utf-8'))
        manifest['version'] = '0.8'
        (resources / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaises(patcher.PatchError):
            patcher.check_resources(resources)

    def test_unicode_source_and_output_roundtrip(self):
        output = self.folder / '한글 완성본.iso'
        result = self.run_patch(output)
        self.assertEqual(output.read_bytes(), self.expected)
        self.assertTrue(result['output_verified_from_disk'])
        self.assertEqual(result['sidecar_status'], 'created')
        self.assertIn('뷰티풀죠 리바이벌', output.with_suffix('.xml').read_text('utf-8'))
        self.assertEqual(patcher.digest(self.source), self.manifest['source']['sha256'])
        self.assert_no_partial()

    def test_existing_output_preserved(self):
        output = self.folder / 'existing.iso'
        output.write_bytes(b'preserve existing file')
        with self.assertRaises(patcher.PatchError):
            self.run_patch(output)
        self.assertEqual(output.read_bytes(), b'preserve existing file')

    def test_source_cannot_be_output(self):
        before = patcher.digest(self.source)
        with self.assertRaises(patcher.PatchError):
            self.run_patch(self.source)
        self.assertEqual(patcher.digest(self.source), before)

    def test_same_size_wrong_source_rejected(self):
        source = self.folder / 'wrong.iso'
        data = bytearray(self.source.read_bytes())
        data[100] ^= 1
        source.write_bytes(data)
        with self.assertRaises(patcher.PatchError):
            patcher.apply_patch(source, self.folder / 'out.iso', resources=self.resources)
        self.assertFalse((self.folder / 'out.iso').exists())
        self.assert_no_partial()

    def test_corrupt_embedded_patch_rejected(self):
        resources = self.folder / 'resources'
        shutil.copytree(self.resources, resources)
        (resources / 'patch.xdelta').write_bytes(b'corruption')
        with self.assertRaises(patcher.PatchError):
            patcher.apply_patch(self.source, self.folder / 'out.iso', resources=resources)
        self.assertFalse((self.folder / 'out.iso').exists())

    def test_bad_result_hash_never_committed(self):
        resources = self.folder / 'resources'
        shutil.copytree(self.resources, resources)
        manifest = json.loads((resources / 'manifest.json').read_text('utf-8'))
        manifest['target']['sha256'] = '1' * 64
        (resources / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')
        with self.assertRaises(patcher.PatchError):
            patcher.apply_patch(self.source, self.folder / 'out.iso', resources=resources)
        self.assertFalse((self.folder / 'out.iso').exists())
        self.assert_no_partial()

    def test_mid_decode_cancel_removes_only_owned_partial(self):
        cancel = threading.Event()
        marker = self.folder / 'keep.txt'
        marker.write_text('keep', encoding='utf-8')
        def progress(phase, value, text):
            if phase == 'decode':
                cancel.set()
        with self.assertRaises(patcher.Cancelled):
            self.run_patch(self.folder / 'out.iso', cancel=cancel, progress=progress)
        self.assertEqual(marker.read_text('utf-8'), 'keep')
        self.assertFalse((self.folder / 'out.iso').exists())
        self.assert_no_partial()

    def test_verify_only_writes_no_result(self):
        result = self.run_patch(verify_only=True)
        self.assertEqual(result['target_sha256'], self.manifest['target']['sha256'])
        self.assertTrue(result['verify_only'])
        self.assertFalse(list(self.folder.iterdir()))

    def test_destination_race_cannot_overwrite(self):
        output = self.folder / 'out.iso'
        commit = patcher._commit_new_file
        def raced(temporary, destination):
            destination.write_bytes(b'other file appeared')
            return commit(temporary, destination)
        with patch.object(patcher, '_commit_new_file', side_effect=raced):
            with self.assertRaises(FileExistsError):
                self.run_patch(output)
        self.assertEqual(output.read_bytes(), b'other file appeared')
        self.assert_no_partial()

    def test_existing_different_xml_is_preserved(self):
        output = self.folder / 'out.iso'
        output.with_suffix('.xml').write_text('<keep />', encoding='utf-8')
        result = self.run_patch(output)
        self.assertEqual(result['sidecar_status'], 'existing_preserved')
        self.assertEqual(output.with_suffix('.xml').read_text('utf-8'), '<keep />')
        self.assertEqual(output.read_bytes(), self.expected)


if __name__ == '__main__':
    unittest.main()
