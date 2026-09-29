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
    root.geometry('640x610')
    root.minsize(600, 580)
    frame = ttk.Frame(root, padding=16)
    frame.pack(fill='both', expand=True)
    path = DATA_DIR / 'config.json'
    try:
        original = json.loads(path.read_text('utf-8'))
    except FileNotFoundError:
        original = asdict(Config('', 0, 0))
    defaults = asdict(Config('', 0, 0))
    tabs = ttk.Notebook(frame)
    tabs.pack(fill='both', expand=True)
    credentials = ttk.Frame(tabs, padding=12)
    options = ttk.Frame(tabs, padding=12)
    tabs.add(credentials, text='Discord 接続')
    tabs.add(options, text='パスワード・表示範囲')
    values = {}
    for key, label in [('bot_token', 'Discord Bot token'), ('channel_id', '申請チャンネル ID'),
                       ('owner_id', '承認者の Discord ユーザー ID')]:
        ttk.Label(credentials, text=label).pack(anchor='w', pady=(8, 0))
        values[key] = tk.StringVar(value=str(original.get(key, '')))
        ttk.Entry(credentials, textvariable=values[key], show='•' if key == 'bot_token' else '').pack(fill='x')
    ttk.Label(options, text='発行する一時パスワード', font=('Yu Gothic UI', 11, 'bold')).pack(anchor='w')
    length_row = ttk.Frame(options)
    length_row.pack(fill='x', pady=(10, 4))
    ttk.Label(length_row, text='桁数（8～64）:').pack(side='left')
    length = tk.StringVar(value=str(original.get('password_length', defaults['password_length'])))
    ttk.Spinbox(length_row, from_=8, to=64, textvariable=length, width=6).pack(side='left', padx=8)
    toggles = {}
    for key, label in [('password_digits', '数字を含める'),
                       ('password_letters', '英字を含める'),
                       ('password_symbols', '記号を含める')]:
        toggles[key] = tk.BooleanVar(value=original.get(key, defaults[key]))
        ttk.Checkbutton(options, text=label, variable=toggles[key]).pack(anchor='w', pady=2)
    ttk.Label(options, text='英字の種類（英字を含める場合）').pack(anchor='w', pady=(9, 2))
    letter_case = tk.StringVar(value=original.get('password_letter_case', defaults['password_letter_case']))
    for value, label in [('lower', '小文字のみ'), ('upper', '大文字のみ'), ('both', '大文字・小文字の両方')]:
        ttk.Radiobutton(options, text=label, variable=letter_case, value=value).pack(anchor='w')
    ttk.Separator(options).pack(fill='x', pady=12)
    ttk.Label(options, text='Discord の表示範囲', font=('Yu Gothic UI', 11, 'bold')).pack(anchor='w')
    ttk.Label(options, text='OFF: 操作した承認者だけに表示 / ON: チャンネル内の全員に表示',
              wraplength=550).pack(anchor='w', pady=(5, 8))
    for key, label in [('ttl_change_public', '有効時間の変更通知をチャンネルに表示'),
                       ('password_public', 'パスワードをチャンネルに表示'),
                       ('expiry_public', 'パスワードの有効期限をチャンネルに表示')]:
        toggles[key] = tk.BooleanVar(value=original.get(key, defaults[key]))
        ttk.Checkbutton(options, text=label, variable=toggles[key]).pack(anchor='w', pady=3)
    ttk.Label(frame, text='保存すると Service を再起動し、有効な一時パスワードを失効させます。'
              '\n表示範囲の変更は次の申請から反映されます。過去のメッセージは削除されません。',
              wraplength=560).pack(anchor='w', pady=14)

    def save():
        try:
            updated = dict(original)
            updated.update(bot_token=values['bot_token'].get().strip(),
                           channel_id=int(values['channel_id'].get()), owner_id=int(values['owner_id'].get()),
                           password_length=int(length.get()), password_letter_case=letter_case.get())
            updated.update({key: variable.get() for key, variable in toggles.items()})
            candidate = Config(**updated)
            if not candidate.bot_token or candidate.channel_id <= 0 or candidate.owner_id <= 0:
                raise ValueError('Bot token と正しい数値の ID を入力してください。')
            candidate.validate()
        except ValueError:
            messagebox.showerror('入力エラー', 'Bot token・ID・桁数（8～64）を確認し、文字種を1つ以上選択してください。')
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
