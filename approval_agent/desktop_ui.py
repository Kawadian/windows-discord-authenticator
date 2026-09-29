"""Settings UI and notification-area icon, running as the interactive user."""
from __future__ import annotations

import ctypes
import json
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import messagebox, ttk

import pystray
from PIL import Image, ImageDraw

from .config import DATA_DIR
from .privacy import Privacy
from .tray import DesktopAgent

PREF_DIR = Path(os.environ.get('LOCALAPPDATA', '.')) / 'UacApproval'


def elevated(executable: Path, arguments: str = ''):
    result = ctypes.windll.shell32.ShellExecuteW(None, 'runas', str(executable), arguments,
                                               str(executable.parent), 1)
    if result <= 32:
        raise OSError('管理者承認がキャンセルされたか、起動できませんでした。')


def main():
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = ctypes.c_void_p
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
    mutex = kernel32.CreateMutexW(None, False, 'Local\\UacApprovalDesktop')
    if kernel32.GetLastError() == 183:
        ctypes.windll.user32.MessageBoxW(None, '起動済みです。通知領域のアイコンから設定を開いてください。',
                                       'UAC Approval', 0)
        return
    root = tk.Tk()
    root.title('UAC Approval — 設定')
    root.geometry('620x640')
    root.minsize(560, 610)
    try:
        privacy = Privacy.parse(json.loads((PREF_DIR / 'privacy.json').read_text('utf-8')))
    except (OSError, ValueError, TypeError, AttributeError):
        privacy = Privacy()
    try:
        client = json.loads((DATA_DIR / 'tray.json').read_text('utf-8'))
    except (OSError, ValueError):
        client = {'port': 53927, 'capture_interval_ms': 750}
    agent = DesktopAgent(int(client['port']), int(client['capture_interval_ms']), privacy)
    agent.start()
    actions = queue.Queue()
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    ttk.Label(frame, text='プライバシーと承認申請', font=('Yu Gothic UI', 17, 'bold')).pack(anchor='w')
    ttk.Label(frame, text='変更はすぐに反映されます。この Windows ユーザーだけに適用されます。',
              wraplength=560).pack(anchor='w', pady=(8, 14))
    status = tk.StringVar()
    variables = {}
    controls = []
    busy = False

    def changed():
        nonlocal busy
        if busy:
            return
        busy = True
        for control in controls:
            control.configure(state='disabled')
        desired = Privacy(**{k: v.get() for k, v in variables.items()})
        status.set('変更中…進行中の処理が終わるまでお待ちください')

        def apply():
            try:
                agent.gate.apply(desired)
                PREF_DIR.mkdir(parents=True, exist_ok=True)
                temporary = PREF_DIR / 'privacy.tmp'
                temporary.write_text(json.dumps(asdict(desired)), encoding='utf-8')
                temporary.replace(PREF_DIR / 'privacy.json')
                actions.put(('applied', '設定を保存しました。撮影 ' + ('ON' if desired.screenshots else 'OFF・保持画像破棄済み')))
            except Exception:
                # Never silently re-enable capture on a persistence/disposal failure.
                agent.gate.close()
                actions.put(('applied', '保存に失敗しました。撮影を停止しました。アプリを再起動してください'))
        threading.Thread(target=apply, daemon=True).start()

    labels = [
        ('screenshots', 'スクリーンショットを撮影・送信する（継続撮影と手動申請）'),
        ('computer', 'PC 名を送信する'), ('user', 'Windows ユーザー名を送信する'),
        ('window', 'ウィンドウのタイトルを取得・送信する'),
        ('process', '最前面のプロセス名を取得・送信する'),
        ('captured_at', '情報の取得時刻を送信する'),
        ('automatic', 'UAC の自動検知と申請を有効にする'),
    ]
    for key, label in labels:
        variables[key] = tk.BooleanVar(value=getattr(privacy, key))
        check = ttk.Checkbutton(frame, text=label, variable=variables[key], command=changed)
        check.pack(anchor='w', pady=5)
        controls.append(check)
    ttk.Label(frame, text='撮影 OFF の反映完了後は撮影 API を呼ばず、カメラと保持画像を破棄します。'
              '\nすでに送信済みの Discord メッセージは取り消せません。'
              '\n自動検知 ON の場合、consent.exe の有無をローカルで確認します。',
              wraplength=560).pack(anchor='w', pady=12)
    ttk.Button(frame, text='承認を申請する（Ctrl + Alt + F12）', command=agent.enqueue).pack(fill='x', pady=4)

    def configure():
        try:
            if getattr(sys, 'frozen', False):
                elevated(Path(sys.executable), '--configure')
            else:
                elevated(Path(sys.executable), '-m approval_agent.desktop_ui --configure')
        except OSError as exc:
            messagebox.showerror('認証設定', str(exc))

    def uninstall():
        exe = Path(sys.executable).parent / 'unins000.exe'
        if not exe.exists():
            messagebox.showerror('アンインストール', 'EXE インストーラーでの導入時のみ利用できます。')
            return
        try:
            elevated(exe)
        except OSError as exc:
            messagebox.showerror('アンインストール', str(exc))

    ttk.Button(frame, text='Bot token・チャンネル・承認者を変更（管理者承認）', command=configure).pack(fill='x', pady=4)
    ttk.Button(frame, text='完全アンインストール（管理者承認）', command=uninstall).pack(fill='x', pady=4)
    ttk.Label(frame, textvariable=status, wraplength=560).pack(anchor='w', pady=12)
    ttk.Label(frame, text='閉じると通知領域に常駐します。終了するにはアイコンのメニューを使ってください。',
              wraplength=560).pack(anchor='w')
    artwork = Image.new('RGB', (64, 64), '#183b56')
    ImageDraw.Draw(artwork).text((18, 20), 'UAC', fill='white')
    icon = pystray.Icon('UacApproval', artwork, 'UAC Approval', pystray.Menu(
        pystray.MenuItem('設定を開く', lambda: actions.put(('show', '')), default=True),
        pystray.MenuItem('承認を申請', lambda: agent.enqueue()),
        pystray.MenuItem('終了（撮影・申請を停止）', lambda: actions.put(('exit', '')))))
    threading.Thread(target=icon.run, daemon=True).start()
    root.protocol('WM_DELETE_WINDOW', root.withdraw)

    def pump():
        nonlocal busy
        try:
            while True:
                action, value = actions.get_nowait()
                if action == 'show':
                    root.deiconify()
                    root.lift()
                elif action == 'exit':
                    agent.close()
                    icon.stop()
                    root.destroy()
                    return
                elif action == 'applied':
                    busy = False
                    status.set(value)
                    for control in controls:
                        control.configure(state='normal')
        except queue.Empty:
            pass
        if not busy and agent.status != '待機中':
            status.set(agent.status)
            agent.status = '待機中'
        root.after(100, pump)
    root.after(100, pump)
    if '--background' in sys.argv:
        root.withdraw()
    root.mainloop()
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel32.CloseHandle(mutex)


if __name__ == '__main__':
    if '--configure' in sys.argv:
        from .settings_ui import main as configure_main
        configure_main()
    else:
        main()
