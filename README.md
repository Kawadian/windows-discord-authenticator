# UAC Approval via Discord

親の Windows PC に表示された UAC の前後で、画面を Discord の専用チャンネルへ送り、管理者が有効時間を指定して一時パスワードを発行する個人用ツールです。公開 Web サーバーやポート開放は使いません。

## 仕組み

- 標準ユーザーのログオン時に `ApprovalTray` が起動し、DXGI Desktop Duplication で通常デスクトップの最新画面 **1 枚だけ**をメモリに保持します。既定は 750 ms 間隔。画面に変化がなければフレームを更新せず、JPEG 圧縮と送信は申請時だけです。自動検知の撮影対象はプライマリモニターです。ホットキーではその場で全モニターを撮影します。
- `consent.exe` の起動やデスクトップ切り替えを検知すると、直前の画面を使って申請します。`Ctrl + Alt + F12` は UAC の有無に関係なく、押した時点の画面で申請します（Secure Desktop の表示中は Windows の制約で反応しません）。
- LocalSystem の Windows Service が Discord Gateway に接続し、指定した管理者の操作だけを受け付けます。発行したパスワードは承認者だけに見える ephemeral 応答で表示します。
- 期限に達すると専用ローカル管理者アカウントのパスワードをランダム値に戻します。Service の監視に加え、SYSTEM の Windows 定期タスクが毎分確認します。再起動時にも古い貸出を失効させます。

## 注意する仕様

- 画面は**実行対象の証明ではありません**。UAC の対象実行ファイルや署名を取得・照合する機能はありません。Discord の画像には、親PCの個人情報が写る可能性があります。
- UAC の事前通知 API はなく、`consent.exe` やデスクトップ切り替え検出はベストエフォートです。画像は通常デスクトップの最大約 750 ms 前のものです。自動検知できない場合はホットキーで申請してください。
- Secure Desktop は既定で有効のままです。UAC の表示中にホットキーで撮影したい場合だけ、Windows の「ユーザー アカウント制御: 管理者承認モードで昇格を要求するときにセキュリティで保護されたデスクトップに切り替える」を無効にできます。設定変更は本ツールで自動実行しません。
- パスワードが有効な間は、その専用管理者アカウントを使う別の UAC 操作にも入力できます。承認は個々の EXE に技術的に紐づきません。期限を短く設定してください。
- Windows が停止している間はパスワードのローテーションを実行できません。再起動時は watchdog タスクが確認します。タスクと Service の両方が停止すると失効できません。
- 親PC上のマルウェアはスクリーンショットを偽装したり、表示中の一時パスワードを盗んだりできます。UAC の代替セキュリティ境界にはなりません。

## 必要なもの

- Windows 10/11、全ユーザー向けにインストールされた Python 3.11 以降、管理者権限での初回セットアップ
- Discord の専用 Bot と、本人しか閲覧できないプライベートチャンネル
- Bot の権限: View Channel / Send Messages / Attach Files / Read Message History。Gateway の特権 Message Content Intent は不要です。Bot に Interaction Endpoint URL を設定しないでください。

## セットアップ

1. Discord Developer Portal で Bot を作成し、プライベートチャンネルに招待します。チャンネル ID と承認する本人のユーザー ID をコピーします。
2. このリポジトリを親PCに配置します。管理者 PowerShell で `powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1` を実行します。スクリプトは全ユーザー向けPythonへ依存パッケージを導入し、`UacApproval` アカウントを新規作成して設定値を質問します。
3. PC を再起動するか、親の標準ユーザーで再ログオンします。トレイ側は `HKLM\...\Run` により起動します。Service と `UacApprovalWatchdog` タスクの状態を確認します。
4. `Ctrl + Alt + F12` で手動申請を試し、Discord に画面付きの申請が届くこと、TTL 選択→発行→UAC 入力→期限切れ後の再利用不可を確認します。

設定ファイルは `%ProgramData%\UacApproval\config.json` に保存され、SYSTEM と Administrators だけが読める ACL にします。Bot Token は Git に入れず、漏えい時は Discord で再発行してください。アンインストール手順は [docs/operations.md](docs/operations.md) を参照してください。

## 開発と確認

依存パッケージの導入後に `python -m unittest discover -s tests`。Windows 固有機能の統合検証には実機が必要です。詳細は [docs/operations.md](docs/operations.md)。

## ライセンス

MIT。
