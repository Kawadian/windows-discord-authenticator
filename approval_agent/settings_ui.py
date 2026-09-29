"""Elevated credential editor. Token never traverses a CLI or loopback endpoint."""
import ctypes
import json
import tkinter as tk
from dataclasses import asdict
from tkinter import messagebox, ttk

import win32security
import win32serviceutil

from .config import Config, DATA_DIR


def protected_write(path, data):
    temporary = path.with_suffix('.new')
    temporary.write_bytes(b'')
    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        'D:P(A;;FA;;;SY)(A;;FA;;;BA)', win32security.SDDL_REVISION_1)
    win32security.SetFileSecurity(str(temporary), win32security.DACL_SECURITY_INFORMATION |
                                 win32security.PROTECTED_DACL_SECURITY_INFORMATION, descriptor)
    temporary.write_text(json.dumps(data), encoding='utf-8')
    temporary.replace(path)


def main():
    if not ctypes.windll.shell32.IsUserAnAdmin():
        raise PermissionError('管理者として実行してください')
    root = tk.Tk()
    root.title('UAC Approval — 認証設定（管理者）')
    root.geometry('600x370')
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill='both', expand=True)
    path = DATA_DIR / 'config.json'
    try:
        original = json.loads(path.read_text('utf-8'))
    except FileNotFoundError:
        original = asdict(Config('', 0, 0))
    values = {}
    for key, label in [('bot_token', 'Discord Bot token'), ('channel_id', '申請チャンネル ID'),
                       ('owner_id', '承認者の Discord ユーザー ID')]:
        ttk.Label(frame, text=label).pack(anchor='w', pady=(8, 0))
        values[key] = tk.StringVar(value=str(original.get(key, '')))
        ttk.Entry(frame, textvariable=values[key], show='•' if key == 'bot_token' else '').pack(fill='x')
    ttk.Label(frame, text='保存すると Service を再起動し、有効な一時パスワードを失効させます。'
              '\n接続先を変更しても、過去の Discord メッセージは削除されません。',
              wraplength=560).pack(anchor='w', pady=14)

    def save():
        try:
            updated = dict(original)
            updated.update(bot_token=values['bot_token'].get().strip(),
                           channel_id=int(values['channel_id'].get()), owner_id=int(values['owner_id'].get()))
            if not updated['bot_token'] or updated['channel_id'] <= 0 or updated['owner_id'] <= 0:
                raise ValueError()
        except ValueError:
            messagebox.showerror('入力エラー', 'Bot token と正しい数値の ID を入力してください。')
            return
        try:
            try:
                win32serviceutil.StopService('UacApprovalService')
            except Exception as exc:
                if getattr(exc, 'winerror', None) != 1062:
                    raise
            win32serviceutil.WaitForServiceStatus('UacApprovalService', 1, 30)
            protected_write(path, updated)
            win32serviceutil.StartService('UacApprovalService')
            win32serviceutil.WaitForServiceStatus('UacApprovalService', 4, 30)
        except Exception:
            messagebox.showerror('保存・起動エラー', 'Service の停止・設定保存・起動のいずれかに失敗しました。'
                                 '設定を確認して再度保存してください。')
            return
        messagebox.showinfo('保存完了', '設定を保存し Service を起動しました。'
                            '\nDiscord への接続確認は、通常の設定画面で承認を申請してください。')
        root.destroy()
    ttk.Button(frame, text='保存して反映', command=save).pack(fill='x')
    root.mainloop()
