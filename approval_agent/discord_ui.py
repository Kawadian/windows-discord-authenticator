"""Discord messages and owner-only controls."""
from __future__ import annotations

import asyncio
import io
import time
import uuid
from dataclasses import dataclass

import discord

from .config import Config
from .lease import LeaseStore


@dataclass
class ApprovalRequest:
    request_id: str
    trigger: str
    computer: str
    user: str
    window: str
    process: str
    captured_at: str
    jpeg: bytes | None
    created_at: float


class CustomTtl(discord.ui.Modal, title="パスワードの有効時間"):
    minutes = discord.ui.TextInput(
        label="分数 (1～30)", placeholder="例: 2", min_length=1, max_length=2
    )

    def __init__(self, view: "ApprovalView"):
        super().__init__()
        self.approval_view = view

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not self.approval_view.authorized(interaction):
            await interaction.response.send_message("この操作は承認者専用です。", ephemeral=True)
            return
        try:
            minutes = int(str(self.minutes.value))
            if not 1 <= minutes <= 30:
                raise ValueError()
        except ValueError:
            await interaction.response.send_message("1～30 分を入力してください。", ephemeral=True)
            return
        self.approval_view.ttl_seconds = minutes * 60
        await interaction.response.send_message(f"有効時間を {minutes} 分に設定しました。発行ボタンを押してください。", ephemeral=True)


class TtlSelect(discord.ui.Select):
    def __init__(self):
        options = [discord.SelectOption(label=label, value=str(seconds)) for label, seconds in
                   [("30 秒", 30), ("1 分", 60), ("3 分", 180), ("5 分", 300),
                    ("10 分", 600), ("30 分", 1800)]]
        options.append(discord.SelectOption(label="任意 (1～30 分)", value="custom"))
        super().__init__(placeholder="有効時間: 1 分", options=options)

    async def callback(self, interaction: discord.Interaction) -> None:
        view = self.view
        if not isinstance(view, ApprovalView) or not view.authorized(interaction):
            await interaction.response.send_message("この操作は承認者専用です。", ephemeral=True)
            return
        if self.values[0] == "custom":
            await interaction.response.send_modal(CustomTtl(view))
            return
        view.ttl_seconds = int(self.values[0])
        await interaction.response.send_message(
            f"有効時間を {view.ttl_seconds} 秒に設定しました。発行ボタンを押してください。", ephemeral=True)


class ApprovalView(discord.ui.View):
    def __init__(self, owner_id: int, account: str, request: ApprovalRequest,
                 store: LeaseStore, request_lifetime: int):
        super().__init__(timeout=request_lifetime)
        self.owner_id = owner_id
        self.account = account
        self.request = request
        self.store = store
        self.ttl_seconds = 60
        self.completed = False
        self.message: discord.Message | None = None
        self.add_item(TtlSelect())

    def authorized(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.owner_id

    @discord.ui.button(label="一時パスワードを発行", style=discord.ButtonStyle.success)
    async def issue(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not self.authorized(interaction):
            await interaction.response.send_message("この操作は承認者専用です。", ephemeral=True)
            return
        if self.completed or time.time() > self.request.created_at + (self.timeout or 0):
            await interaction.response.send_message("この申請は失効しています。", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            secret, expires_at = await asyncio.to_thread(self.store.issue, self.ttl_seconds)
        except Exception:
            await interaction.followup.send("発行できませんでした。すでに有効なパスワードがないか、Service の状態を確認してください。", ephemeral=True)
            return
        try:
            await interaction.followup.send(
                f"**{self.request.computer}** の一時パスワード\n"
                f"アカウント: `.\\{self.account}`\n"
                f"**`{secret}`**\n有効期限: <t:{int(expires_at)}:F> (<t:{int(expires_at)}:R>)",
                ephemeral=True,
            )
        except Exception:
            # If delivery fails, do not leave an undisclosed valid password behind.
            await asyncio.to_thread(self.store.rotate)
            raise
        self.completed = True
        for item in self.children:
            item.disabled = True
        try:
            await interaction.message.edit(content=interaction.message.content + "\n✅ 発行済み", view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="拒否", style=discord.ButtonStyle.danger)
    async def deny(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        if not self.authorized(interaction):
            await interaction.response.send_message("この操作は承認者専用です。", ephemeral=True)
            return
        self.completed = True
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(content=interaction.message.content + "\n❌ 拒否", view=self)

    async def on_timeout(self) -> None:
        self.completed = True
        for item in self.children:
            item.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class ApprovalBot(discord.Client):
    def __init__(self, config: Config, store: LeaseStore):
        super().__init__(intents=discord.Intents.none())
        self.config = config
        self.store = store
        self.ready_for_requests = asyncio.Event()

    async def on_ready(self) -> None:
        self.ready_for_requests.set()

    async def on_disconnect(self) -> None:
        self.ready_for_requests.clear()

    async def post_request(self, payload: dict, jpeg: bytes | None) -> None:
        await self.ready_for_requests.wait()
        channel = self.get_channel(self.config.channel_id)
        if channel is None:
            channel = await self.fetch_channel(self.config.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise RuntimeError("The configured channel is not a text channel")
        request = ApprovalRequest(
            request_id=uuid.uuid4().hex,
            trigger=payload["trigger"], computer=payload["computer"],
            user=payload["user"], window=payload["window"],
            process=payload["process"], captured_at=payload["captured_at"],
            jpeg=jpeg, created_at=time.time(),
        )
        view = ApprovalView(self.config.owner_id, self.config.admin_account, request, self.store,
                            self.config.request_lifetime_seconds)
        content = (f"<@{self.config.owner_id}> 🔐 管理者承認申請\n"
                   f"PC: `{request.computer}` / ユーザー: `{request.user}`\n"
                   f"検知: `{request.trigger}` / 情報取得時刻: `{request.captured_at}`\n"
                   f"直前のウィンドウ: `{request.window}`\n"
                   f"直前のプロセス: `{request.process}`\n"
                   "この情報は UAC の実行対象を証明するものではありません。")
        files = [discord.File(io.BytesIO(jpeg), filename="desktop.jpg")] if jpeg else []
        view.message = await channel.send(
            content, files=files, view=view,
            allowed_mentions=discord.AllowedMentions(
                users=[discord.Object(id=self.config.owner_id)],
                everyone=False, roles=False),
        )
