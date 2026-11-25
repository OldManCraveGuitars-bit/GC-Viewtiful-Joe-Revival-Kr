"""SPDX-License-Identifier: MIT
Viewtiful Joe Revival Korean patcher: verified, non-destructive ISO application.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import xml.etree.ElementTree as ET

VERSION = '0.9'
REVISION = 'v0.9'
BLOCK = 1024 * 1024


class PatchError(Exception):
    pass


class Cancelled(PatchError):
    pass


def resource_root():
    return Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent)) / 'resources'


def digest(path, cancel=None, progress=None):
    result = hashlib.sha256()
    total = Path(path).stat().st_size
    done = 0
    with Path(path).open('rb') as stream:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled('작업을 취소했습니다. 원본은 변경되지 않았습니다.')
            data = stream.read(4 * BLOCK)
            if not data:
                break
            result.update(data)
            done += len(data)
            if progress:
                progress(done / max(1, total))
    return result.hexdigest()


def check_resources(resources=None):
    root = Path(resources) if resources else resource_root()
    try:
        manifest = json.loads((root / 'manifest.json').read_text('utf-8'))
        if manifest['schema'] != 1 or manifest['version'] != VERSION:
            raise ValueError('version')
        for key in ('patch', 'decoder', 'sidecar'):
            item = manifest[key]
            name = item['name']
            if Path(name).name != name or '/' in name or '\\' in name:
                raise ValueError('resource path')
            path = root / name
            if path.stat().st_size != item['size'] or digest(path) != item['sha256']:
                raise ValueError('resource hash: ' + name)
        for key in ('source', 'target'):
            item = manifest[key]
            if item['size'] <= 0 or len(item['sha256']) != 64 or any(c not in '0123456789abcdef' for c in item['sha256']):
                raise ValueError('image fingerprint')
        app = ET.parse(root / manifest['sidecar']['name']).getroot()
        if app.tag != 'app' or not all(app.findtext(key) for key in ('name', 'coder', 'short_description')):
            raise ValueError('title XML')
    except (OSError, KeyError, TypeError, ValueError, ET.ParseError) as exc:
        raise PatchError('패처 내부 파일을 확인할 수 없습니다. 공식 릴리스에서 다시 받아 주세요.\n' + str(exc)) from exc
    return root, manifest


def _decode(root, manifest, source, sink, cancel, progress):
    command = [str(root / manifest['decoder']['name']), '-d', '-c', '-s', str(source),
               str(root / manifest['patch']['name'])]
    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    errors = bytearray()
    finished = threading.Event()

    def read_errors():
        for chunk in iter(lambda: proc.stderr.read(4096), b''):
            errors.extend(chunk)
            if len(errors) > 16384:
                del errors[:-16384]

    def watch_cancel():
        while not finished.wait(.1):
            if cancel.is_set():
                try:
                    proc.terminate()
                except OSError:
                    pass
                return

    reader = threading.Thread(target=read_errors, daemon=True)
    watcher = threading.Thread(target=watch_cancel, daemon=True)
    reader.start()
    watcher.start()
    hasher = hashlib.sha256()
    total = 0
    try:
        while True:
            if cancel.is_set():
                raise Cancelled('작업을 취소했습니다. 원본은 변경되지 않았습니다.')
            data = proc.stdout.read(BLOCK)
            if not data:
                break
            total += len(data)
            if total > manifest['target']['size']:
                raise PatchError('결과 파일 크기가 예상 범위를 넘었습니다.')
            if sink is not None:
                sink.write(data)
            hasher.update(data)
            progress('decode', total / manifest['target']['size'],
                     f'한글 패치 적용 중  {total / BLOCK:,.0f} / {manifest["target"]["size"] / BLOCK:,.0f} MB')
        code = proc.wait(timeout=15)
        reader.join(timeout=5)
        if cancel.is_set():
            raise Cancelled('작업을 취소했습니다. 원본은 변경되지 않았습니다.')
        if code:
            raise PatchError('패치 적용에 실패했습니다.\n' + errors.decode('utf-8', 'replace')[-1600:])
        if total != manifest['target']['size'] or hasher.hexdigest() != manifest['target']['sha256']:
            raise PatchError('완성 파일의 크기 또는 SHA-256이 일치하지 않습니다.')
        return hasher.hexdigest(), total
    finally:
        finished.set()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
        reader.join(timeout=5)
        watcher.join(timeout=1)
        proc.stdout.close()
        proc.stderr.close()


def _commit_new_file(temporary, output):
    if os.name == 'nt':
        # Windows rename is atomic and rejects an existing destination.
        os.rename(temporary, output)
    else:
        # Unlike POSIX rename, link cannot replace an existing destination.
        os.link(temporary, output)
        temporary.unlink()


def apply_patch(source, output=None, *, verify_only=False, resources=None, cancel=None,
                progress=lambda phase, value, text: None):
    cancel = cancel if cancel is not None else threading.Event()
    root, manifest = check_resources(resources)
    source = Path(source).expanduser().resolve(strict=True)
    if not source.is_file():
        raise PatchError('일본판 원본 ISO/GCM 파일을 선택하세요.')
    if source.suffix.lower() not in ('.iso', '.gcm'):
        raise PatchError('압축을 푼 원본 ISO/GCM이 필요합니다. RVZ는 돌핀에서 ISO로 변환한 뒤 선택하세요.')
    destination = None
    if not verify_only:
        if output is None:
            raise PatchError('완성 ISO를 저장할 위치를 선택하세요.')
        destination = Path(output).expanduser().resolve()
        if destination == source:
            raise PatchError('원본 파일에는 덮어쓸 수 없습니다. 새 출력 파일을 선택하세요.')
        if destination.exists():
            raise PatchError('출력 파일이 이미 있습니다. 기존 파일을 보존하려면 새 이름을 선택하세요.')
        if destination.suffix.lower() != '.iso' or not destination.parent.is_dir():
            raise PatchError('존재하는 폴더 안에 새 ISO 파일 이름을 지정하세요.')
        if shutil.disk_usage(destination.parent).free < manifest['target']['size'] + 64 * BLOCK:
            raise PatchError('완성 ISO를 저장할 공간이 부족합니다. 약 1.5 GB 이상의 여유 공간이 필요합니다.')
    if source.stat().st_size != manifest['source']['size']:
        raise PatchError(f'지원하는 원본은 일본판 GVFJ08, {manifest["source"]["size"]:,}바이트입니다.\n'
                         '다른 지역판·압축 파일·이미 패치한 파일에는 적용할 수 없습니다.')
    before = source.stat()
    actual = digest(source, cancel, lambda value: progress('source', value, f'일본판 원본 확인 중  {value:.0%}'))
    if actual != manifest['source']['sha256']:
        raise PatchError('원본 SHA-256이 일치하지 않습니다. 일본판의 수정되지 않은 원본 ISO가 필요합니다.\n'
                         '기대: ' + manifest['source']['sha256'] + '\n선택: ' + actual)
    if (source.stat().st_mtime_ns, source.stat().st_size) != (before.st_mtime_ns, before.st_size):
        raise PatchError('원본 파일이 검사 중 변경되었습니다. 다시 선택하세요.')
    temporary = None
    try:
        if verify_only:
            decoded, size = _decode(root, manifest, source, None, cancel, progress)
        else:
            fd, name = tempfile.mkstemp(prefix='.vjkr-', suffix='.partial', dir=destination.parent)
            temporary = Path(name)
            with os.fdopen(fd, 'wb') as sink:
                decoded, size = _decode(root, manifest, source, sink, cancel, progress)
                sink.flush()
                os.fsync(sink.fileno())
            disk_hash = digest(temporary, cancel,
                               lambda value: progress('verify', value, f'저장된 ISO 최종 검사 중  {value:.0%}'))
            if disk_hash != manifest['target']['sha256']:
                raise PatchError('저장된 ISO 검사에 실패했습니다. 결과 파일을 확정하지 않았습니다.')
            if cancel.is_set():
                raise Cancelled('작업을 취소했습니다. 원본은 변경되지 않았습니다.')
            _commit_new_file(temporary, destination)
            temporary = None
        sidecar_status = 'not_requested'
        if destination is not None:
            sidecar = destination.with_suffix('.xml')
            content = (root / manifest['sidecar']['name']).read_bytes()
            try:
                with sidecar.open('xb') as stream:
                    stream.write(content)
                sidecar_status = 'created'
            except FileExistsError:
                sidecar_status = 'existing_matching' if sidecar.read_bytes() == content else 'existing_preserved'
            except OSError:
                sidecar_status = 'could_not_write'
        progress('finish', 1, '한글 패치와 완성 ISO 검사가 끝났습니다.')
        return dict(status='passed', version=VERSION, source_sha256=actual,
                    target_sha256=decoded, target_size=size,
                    output=str(destination) if destination else None, verify_only=verify_only,
                    output_verified_from_disk=not verify_only, sidecar_status=sidecar_status,
                    source_overwritten=False)
    finally:
        # Delete only this invocation's newly created incomplete file.
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def make_gui():
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    class Window(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title('뷰티풀죠 리바이벌 · 한국어 패처 v0.9')
            self.geometry('820x650')
            self.minsize(760, 620)
            self.source = tk.StringVar()
            self.output = tk.StringVar()
            self.status = tk.StringVar(value='일본판 원본 ISO/GCM을 선택하세요.')
            self.elapsed = tk.StringVar(value='')
            self.events = queue.Queue()
            self.cancel_event = threading.Event()
            self.busy = False
            self.closing = False
            self.started = 0
            self.last_result = None
            container = ttk.Frame(self, padding=20)
            container.pack(fill='both', expand=True)
            top = ttk.Frame(container)
            top.pack(fill='x')
            self.art = tk.PhotoImage(file=str(resource_root() / 'title.png')).subsample(2, 2)
            ttk.Label(top, image=self.art).pack(side='left', padx=(0, 22))
            intro = ttk.Frame(top)
            intro.pack(side='left', fill='both', expand=True)
            ttk.Label(intro, text='뷰티풀죠 리바이벌', font=('맑은 고딕', 19, 'bold')).pack(anchor='w', pady=(10, 4))
            ttk.Label(intro, text='GameCube 한국어 패치  v0.9', font=('맑은 고딕', 12)).pack(anchor='w')
            ttk.Label(intro, text='일본판 GVFJ08 전용\n\n원본 확인 → 패치 적용 → 완성 파일 검사\n\nRVZ는 먼저 돌핀에서 ISO로 변환하세요.',
                      justify='left', wraplength=385).pack(anchor='w', pady=15)
            ttk.Label(intro, text='한글화 기타 깍는 노인').pack(anchor='w')
            self.entries = []
            self.browse_buttons = []
            for label, variable, callback in [('원본 ISO / GCM', self.source, self.choose_source),
                                               ('저장할 새 ISO', self.output, self.choose_output)]:
                ttk.Label(container, text=label).pack(anchor='w', pady=(16, 4))
                row = ttk.Frame(container)
                row.pack(fill='x')
                entry = ttk.Entry(row, textvariable=variable)
                entry.pack(side='left', fill='x', expand=True)
                button = ttk.Button(row, text='찾아보기', command=callback)
                button.pack(side='right', padx=(8, 0))
                self.entries.append(entry)
                self.browse_buttons.append(button)
            ttk.Label(container, textvariable=self.status, wraplength=735).pack(anchor='w', pady=(20, 7))
            self.bar = ttk.Progressbar(container, maximum=100)
            self.bar.pack(fill='x')
            ttk.Label(container, textvariable=self.elapsed).pack(anchor='e', pady=3)
            buttons = ttk.Frame(container)
            buttons.pack(fill='x', pady=12)
            self.start_button = ttk.Button(buttons, text='한글 패치 시작', command=self.start)
            self.start_button.pack(side='left')
            self.cancel_button = ttk.Button(buttons, text='취소', state='disabled', command=self.cancel_event.set)
            self.cancel_button.pack(side='left', padx=10)
            self.folder_button = ttk.Button(buttons, text='저장 폴더 열기', state='disabled', command=self.open_folder)
            self.folder_button.pack(side='right')
            ttk.Label(container, text='원본은 보존하며, 기존 출력 파일을 덮어쓰지 않습니다.').pack(anchor='w')
            self.protocol('WM_DELETE_WINDOW', self.close_requested)
            self.after(100, self.pump)

        def choose_source(self):
            path = filedialog.askopenfilename(title='일본판 원본 선택', filetypes=[('ISO / GCM', '*.iso *.gcm'), ('모든 파일', '*.*')])
            if path:
                self.source.set(path)
                if not self.output.get():
                    self.output.set(str(Path(path).parent / 'Viewtiful-Joe-Revival-Kr-v0.9.iso'))

        def choose_output(self):
            path = filedialog.asksaveasfilename(title='새 ISO 저장 위치', defaultextension='.iso',
                                               initialfile='Viewtiful-Joe-Revival-Kr-v0.9.iso', filetypes=[('ISO', '*.iso')])
            if path:
                self.output.set(path)

        def set_busy(self, busy):
            self.busy = busy
            for widget in self.entries + self.browse_buttons + [self.start_button]:
                widget.configure(state='disabled' if busy else 'normal')
            self.cancel_button.configure(state='normal' if busy else 'disabled')

        def start(self):
            if self.busy:
                return
            if not self.source.get() or not self.output.get():
                messagebox.showinfo('파일 선택', '원본 ISO/GCM과 저장할 새 ISO를 지정하세요.', parent=self)
                return
            self.cancel_event.clear()
            self.started = time.monotonic()
            self.bar['value'] = 0
            self.folder_button.configure(state='disabled')
            self.set_busy(True)
            source, output = self.source.get(), self.output.get()

            def worker():
                try:
                    result = apply_patch(source, output, cancel=self.cancel_event,
                                         progress=lambda *event: self.events.put(('progress', event)))
                    self.events.put(('done', result))
                except Exception as exc:
                    self.events.put(('error', str(exc)))

            threading.Thread(target=worker, daemon=True).start()

        def pump(self):
            try:
                while True:
                    kind, event = self.events.get_nowait()
                    if kind == 'progress':
                        phase, value, text = event
                        base, span = {'source': (0, 25), 'decode': (25, 65), 'verify': (90, 10), 'finish': (100, 0)}[phase]
                        self.bar['value'] = base + span * value
                        self.status.set(text)
                    else:
                        self.set_busy(False)
                        if kind == 'done':
                            self.last_result = event
                            self.folder_button.configure(state='normal')
                            text = '완성 ISO와 돌핀 표시 이름용 XML을 저장했습니다.\n' + event['output']
                            if event['sidecar_status'] in ('existing_preserved', 'could_not_write'):
                                text = '완성 ISO는 정상입니다. 표시 이름용 XML은 별도로 확인하세요.\n' + event['output']
                            self.status.set(text)
                            if not self.closing:
                                messagebox.showinfo('패치 완료', text, parent=self)
                        else:
                            self.status.set(event)
                            if not self.closing:
                                messagebox.showerror('패치 중단', event, parent=self)
                        if self.closing:
                            self.destroy()
                            return
            except queue.Empty:
                pass
            if self.busy:
                self.elapsed.set(f'경과 시간 {int(time.monotonic() - self.started)}초')
            self.after(100, self.pump)

        def open_folder(self):
            if self.last_result and os.name == 'nt':
                os.startfile(str(Path(self.last_result['output']).parent))

        def close_requested(self):
            if self.busy:
                self.closing = True
                self.cancel_event.set()
                self.status.set('작업을 취소하고 있습니다…')
            else:
                self.destroy()

    return Window()


def main():
    parser = argparse.ArgumentParser(description='Viewtiful Joe Revival Korean patcher v0.9')
    parser.add_argument('--source', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--self-check', action='store_true')
    parser.add_argument('--gui-check', action='store_true')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if not (args.source or args.output or args.verify_only or args.self_check or args.gui_check):
        app = make_gui()
        app.mainloop()
        return 0
    try:
        if args.gui_check:
            app = make_gui()
            app.update()
            result = dict(status='passed', version=VERSION, frozen=bool(getattr(sys, 'frozen', False)),
                          title=app.title(), width=app.winfo_width(), height=app.winfo_height(),
                          image_width=app.art.width(), source_and_output_fields=len(app.entries),
                          start_enabled=str(app.start_button['state']) == 'normal',
                          cancel_initially_disabled=str(app.cancel_button['state']) == 'disabled')
            assert result['width'] >= 760 and result['height'] >= 620 and result['source_and_output_fields'] == 2
            assert result['start_enabled'] and result['cancel_initially_disabled'] and result['image_width'] > 0
            app.destroy()
        elif args.self_check:
            _, manifest = check_resources()
            result = dict(status='passed', version=VERSION, frozen=bool(getattr(sys, 'frozen', False)),
                          game_id=manifest['game_id'], source_sha256=manifest['source']['sha256'],
                          target_sha256=manifest['target']['sha256'], resources_verified=True)
        else:
            if args.source is None:
                raise PatchError('원본 ISO/GCM을 지정하세요.')
            result = apply_patch(args.source, args.output, verify_only=args.verify_only)
        code = 0
    except Exception as exc:
        result = dict(status='failed', version=VERSION, error=str(exc))
        code = 1
    result['revision'] = REVISION
    if args.report:
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    if sys.stdout:
        print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
