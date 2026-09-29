# 運用・検証

## Discord の準備

Developer Portal で Bot を作成し、Bot Token を取得します。専用のプライベートチャンネルには本人と Bot だけがアクセスできるようにします。Bot に `View Channel`、`Send Messages`、`Attach Files`、`Read Message History` を付与します。Bot の Gateway Intent は最低限で足り、Message Content Intent は使用しません。

申請メッセージの画像・ウィンドウ名は Discord 側に残ります。不要になった申請は手動で削除してください。一時パスワードはチャンネル本文には残さず、承認者だけへの ephemeral 応答に表示します。Discord の表示を持つ本人のアカウントは二要素認証を有効にしてください。

## Windows 実機での確認

1. `Get-Service UacApprovalService` が Running、`Get-ScheduledTask UacApprovalWatchdog*` が登録済み、`Get-LocalUser UacApproval` が Enabled であることを確認します。
2. 親の標準ユーザーでサインインして `Ctrl + Alt + F12` を押し、本人の Discord にスクリーンショットが届くことを確認します。
3. 有効時間を 30 秒にして発行し、UAC に `.\UacApproval` と表示されたパスワードを入力します。期限後に同じパスワードで二度目の UAC が通らないことを確認します。
4. Service を停止して有効時間を超え、定期タスクが失効させることを確認します。停止テストの前には、PC にアクセスできる別の管理者アカウントを用意してください。
5. 通常デスクトップで突然 UAC が出るケースを複数回試し、直前画面が送られる頻度・PC の負荷を確認します。検出できない環境では `Ctrl + Alt + F12` を使います。

自動撮影はプライマリモニターのみを対象にし、DXGI が新しいフレームを返したときだけ最新画面を更新します。ホットキーによる撮影は全モニターをその場で取得します。実機ではタスクマネージャーで CPU とメモリ使用量を確認し、負荷が気になる場合は `capture_interval_ms` を 1000～2000 に調整してください。

## 設定変更と更新

`%ProgramData%\UacApproval\config.json` は管理者と SYSTEM のみ読み書きできます。Token や ID の変更後は Service を再起動します。撮影間隔とポートを変える場合は `tray.json` の値もそろえて、親ユーザーのセッションを再ログオンします。interval は 200～5000 ms です。再起動は有効中のパスワードを失効させます。

コード更新では管理者として Service を停止し、保護された `%ProgramFiles%\UacApproval\source` を新しいファイルで置き換え、仮想環境の `python.exe -m pip install <source のパス>` を実行して Service を開始します。動いている標準ユーザー側の Tray は再ログオンして更新します。ユーザー書き込み可能なディレクトリから SYSTEM 権限で新しいコードを実行しないでください。

## 期限と障害

Service は起動時と正常停止時に専用管理者アカウントのパスワードをローテーションします。発行時に期限だけを保護された `state.json` に保存し、Service が 0.5 秒間隔、独立した SYSTEM タスクが毎分期限を検査します。タスクの毎分実行には最大約 1 分の遅れがあります。Windows 自体が停止している間の失効は、次の起動時まで実行できません。

Discord が接続できないときは新しい申請の受付を停止します。すでに発行済みのパスワードの期限は、Discord 接続の有無に左右されません。サービスとタスクの両方が停止すると期限失効は保証されません。

## アンインストール

管理者 PowerShell から `powershell -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1` を実行します。専用管理者アカウントも削除する場合は `-RemoveAccount` を付けます。別の管理者でログインできることを確認してから実行してください。Token を含む `%ProgramData%\UacApproval` とプログラムは、内容を確認してから手動で削除します。
