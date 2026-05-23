from collections import deque
import asyncio
import time
from typing import cast

import discord
from discord.ext import commands
import wavelink

MIKU_COLOR = 0x39C5BB
MIKU_GIF = "https://i.imgur.com/RAZggjC.gif"
MAX_QUEUE_SIZE = 100
QUEUE_DISPLAY_LIMIT = 15
QUEUE_VIEW_TIMEOUT = 30
QUEUE_PAGE_SIZE = 10


def create_progress_bar(progress, total, length=14):
    if total <= 0:
        total = 1

    filled = int(length * progress / total)

    return (
        "▰" * filled +
        "▱" * (length - filled)
    )


def format_time(seconds):
    minutes = int(seconds // 60)
    seconds = int(seconds % 60)

    return f"{minutes:02}:{seconds:02}"


def create_miku_embed(title, description):
    embed = discord.Embed(
        title=title,
        description=description,
        color=MIKU_COLOR
    )

    embed.set_footer(
        text="♪ Hatsune Miku Music System ✨"
    )

    embed.set_image(
        url=MIKU_GIF
    )

    return embed


class MusicControlView(discord.ui.View):
    def __init__(self, cog):
        super().__init__(timeout=None)
        self.cog = cog

    async def interaction_check(self, interaction):
        vc = interaction.guild.voice_client

        error_message = self.cog._validate_voice_access(
            interaction.user,
            vc,
        )

        if error_message:
            await interaction.response.send_message(
                error_message,
                ephemeral=True
            )
            return False

        return True

    @discord.ui.button(
        label="Pause / Resume",
        emoji="⏯️",
        style=discord.ButtonStyle.primary
    )
    async def toggle_pause(
        self,
        interaction,
        _button,
    ):
        vc: wavelink.Player = interaction.guild.voice_client

        if vc.paused:
            await vc.pause(False)

            await interaction.response.send_message(
                "▶️ Musik dilanjutkan~",
                ephemeral=True
            )

        else:
            await vc.pause(True)

            await interaction.response.send_message(
                "⏸️ Musik dijeda~",
                ephemeral=True
            )

    @discord.ui.button(
        label="Skip",
        emoji="⏭️",
        style=discord.ButtonStyle.secondary
    )
    async def skip(
        self,
        interaction,
        _button,
    ):
        vc: wavelink.Player = interaction.guild.voice_client

        if vc:
            self.cog.is_looping[
                interaction.guild.id
            ] = False

            await vc.skip()

            await interaction.response.send_message(
                f"⏭️ Lagu dilewati oleh {interaction.user.mention}",
                ephemeral=False
            )

    @discord.ui.button(
        label="Stop",
        emoji="⏹️",
        style=discord.ButtonStyle.danger
    )
    async def stop_button(
        self,
        interaction,
        _button,
    ):
        vc: wavelink.Player = interaction.guild.voice_client

        if vc:
            self.cog._reset_guild_state(interaction.guild.id)

            vc.queue.clear()

            await vc.stop()

            await interaction.response.send_message(
                "⏹️ Musik dihentikan~",
                ephemeral=False
            )


class QueuePaginationView(discord.ui.View):
    def __init__(self, cog, guild_id, requester_id):
        super().__init__(timeout=QUEUE_VIEW_TIMEOUT)
        self.cog = cog
        self.guild_id = guild_id
        self.requester_id = requester_id
        self.current_page = 0
        self.message: discord.Message | None = None

    def _get_total_pages(self):
        queue = self.cog.music_queue.get(self.guild_id) or []
        return max(1, (len(queue) + QUEUE_PAGE_SIZE - 1) // QUEUE_PAGE_SIZE)

    def _update_button_states(self):
        total_pages = self._get_total_pages()
        buttons = [item for item in self.children if isinstance(item, discord.ui.Button)]
        if len(buttons) < 2:
            return

        prev_button = cast(discord.ui.Button, buttons[0])
        next_button = cast(discord.ui.Button, buttons[1])
        prev_button.disabled = self.current_page <= 0
        next_button.disabled = self.current_page >= total_pages - 1

    async def _refresh_message(self, interaction):
        queue = self.cog.music_queue.get(self.guild_id)
        if not queue:
            await interaction.response.edit_message(
                embed=create_miku_embed("📭 Queue kosong~", "Tidak ada lagu di queue."),
                view=None,
            )
            self.stop()
            return

        total_pages = self._get_total_pages()
        self.current_page = min(self.current_page, total_pages - 1)
        embed = self.cog._build_queue_embed(queue, self.current_page, total_pages)
        self._update_button_states()
        await interaction.response.edit_message(embed=embed, view=self)

    async def interaction_check(self, interaction):
        if interaction.user.id != self.requester_id:
            await interaction.response.send_message(
                "❌ Hanya yang menjalankan command yang bisa pakai tombol queue.",
                ephemeral=True,
            )
            return False

        return True

    @discord.ui.button(label="Prev", emoji="⬅️", style=discord.ButtonStyle.secondary)
    async def prev_button(self, interaction, _button):
        self.current_page = max(0, self.current_page - 1)
        await self._refresh_message(interaction)

    @discord.ui.button(label="Next", emoji="➡️", style=discord.ButtonStyle.primary)
    async def next_button(self, interaction, _button):
        self.current_page += 1
        await self._refresh_message(interaction)

    async def on_timeout(self):
        if not self.message:
            return

        try:
            await self.message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass


class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

        self.music_queue = {}
        self.current_song = {}
        self.is_looping = {}
        self.song_start_time = {}

    def _make_song_entry(self, track, requester, message=None):
        return {
            "track": track,
            "requester": requester,
            "message": message,
        }

    def _get_track_title(self, track):
        return getattr(track, "title", "Unknown Title")

    def _get_track_duration(self, track):
        return int(getattr(track, "length", 0) / 1000)

    def _get_requester(self, guild_id):
        return self.current_song.get(guild_id, {}).get("requester", "Unknown")

    def _get_track_thumbnail(self, track):
        if getattr(track, "artwork", None):
            return track.artwork

        return getattr(track, "thumbnail", None)

    def _build_now_playing_embed(self, track, requester, current=None, duration=None):
        if current is None or duration is None:
            description = f"✨ **{self._get_track_title(track)}**"
        else:
            progress_bar = create_progress_bar(current, duration)
            description = (
                f"✨ **{self._get_track_title(track)}**\n\n"
                f"`{format_time(current)}`\n"
                f"{progress_bar}\n"
                f"`{format_time(duration)}`\n\n"
                "══✦══✦══✦══\n\n"
                f"🎤 Requested by:\n{requester}"
            )

        embed = create_miku_embed("💙 ♪ NOW SINGING ♪ 💙", description)
        thumbnail = self._get_track_thumbnail(track)
        if thumbnail:
            embed.set_thumbnail(url=thumbnail)

        return embed

    def _reset_guild_state(self, guild_id):
        self.music_queue[guild_id] = deque()
        self.is_looping[guild_id] = False

    def _get_or_create_queue(self, guild_id):
        if guild_id not in self.music_queue:
            self.music_queue[guild_id] = deque()

        return self.music_queue[guild_id]

    def _should_loop_current_track(self, guild_id):
        return self.is_looping.get(guild_id, False) and guild_id in self.current_song

    def _parse_search_result(self, search_result):
        if isinstance(search_result, wavelink.Playlist):
            return {
                "is_playlist": True,
                "name": getattr(search_result, "name", "Unknown Playlist"),
                "tracks": list(search_result),
            }

        return {
            "is_playlist": False,
            "name": None,
            "tracks": list(search_result),
        }

    def _append_tracks_to_queue(self, guild_id, tracks, requester):
        queue = self._get_or_create_queue(guild_id)
        available_slots = max(0, MAX_QUEUE_SIZE - len(queue))
        tracks_to_add = tracks[:available_slots]

        for track in tracks_to_add:
            queue.append(self._make_song_entry(track, requester))

        return len(tracks_to_add), len(tracks) - len(tracks_to_add)

    def _build_queue_embed(self, queue, page=0, total_pages=1):
        start = page * QUEUE_PAGE_SIZE
        end = start + QUEUE_PAGE_SIZE
        page_items = list(queue)[start:end]

        lines = []
        for index, song in enumerate(page_items, start=start + 1):
            track = song["track"]
            lines.append(f"╭─ 🎵 `{index}`\n╰─ {self._get_track_title(track)}")

        remaining = len(queue) - end
        if remaining > 0:
            lines.append(f"...dan **{remaining}** lagu lagi.")

        return create_miku_embed(
            f"📜 Miku Queue ({len(queue)}) • Page {page + 1}/{total_pages}",
            "\n\n".join(lines),
        )

    async def _delete_message_after(self, message, delay):
        await asyncio.sleep(delay)
        try:
            await message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

    def _pop_next_song(self, guild_id):
        if self._should_loop_current_track(guild_id):
            return self.current_song[guild_id]

        queue = self.music_queue.get(guild_id)
        if queue:
            return queue.popleft()

        return None

    async def _send_now_playing_message(self, player, guild_id, track):
        channel = player.guild.get_channel(player.channel.id)
        if channel is None:
            return None

        embed = self._build_now_playing_embed(
            track,
            self._get_requester(guild_id),
        )

        try:
            return await channel.send(embed=embed, view=MusicControlView(self))
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            return None

    async def _start_track(self, player, guild_id, track, message=None):
        self.song_start_time[guild_id] = time.time()
        await player.play(track)

        if message is None:
            message = await self._send_now_playing_message(player, guild_id, track)
        else:
            embed = self._build_now_playing_embed(
                track,
                self._get_requester(guild_id),
            )
            try:
                await message.edit(embed=embed, view=MusicControlView(self))
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                message = await self._send_now_playing_message(player, guild_id, track)

        if message:
            self.current_song[guild_id]["message"] = message
            self.bot.loop.create_task(self.update_progress_bar(message, guild_id, track))

    def _validate_voice_access(self, user, vc):
        if not vc:
            return "🎧 Miku tidak ada di VC~"

        if not user.voice:
            return "🎤 Masuk VC dulu yaa~"

        if user.voice.channel != vc.channel:
            return "❌ Kamu harus berada di VC yang sama!"

        return None

    async def _ensure_author_in_voice(self, ctx):
        if ctx.author.voice:
            return True

        await ctx.send("🎤 Masuk VC dulu yaa~")
        return False

    async def _ensure_same_voice_channel(self, ctx):
        vc: wavelink.Player = ctx.voice_client
        error_message = self._validate_voice_access(ctx.author, vc)
        if error_message:
            await ctx.send(error_message)
            return None

        return vc

    async def auto_disconnect(self, vc):
        await asyncio.sleep(300)

        if vc and not vc.playing:
            await vc.disconnect()

    async def update_progress_bar(self, message, guild_id, track):
        while True:
            guild = self.bot.get_guild(guild_id)
            if guild is None:
                break

            vc = guild.voice_client
            current_song = self.current_song.get(guild_id)
            if not vc or not vc.playing or not current_song or current_song.get("track") != track:
                break

            current = int(time.time() - self.song_start_time.get(guild_id, time.time()))
            duration = self._get_track_duration(track)
            embed = self._build_now_playing_embed(
                track,
                self._get_requester(guild_id),
                current,
                duration,
            )

            try:
                await message.edit(embed=embed, view=MusicControlView(self))
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                break
            await asyncio.sleep(10)

    async def play_next(self, player, guild_id):
        old_song = self.current_song.get(guild_id)
        if old_song and old_song.get("message"):
            try:
                await old_song["message"].delete()
            except (discord.Forbidden, discord.NotFound, discord.HTTPException):
                pass

        next_song = self._pop_next_song(guild_id)
        if not next_song:
            self.current_song.pop(guild_id, None)
            return

        self.current_song[guild_id] = next_song
        await self._start_track(player, guild_id, next_song["track"])

    @commands.Cog.listener()
    async def on_wavelink_track_end(self, payload):
        player = getattr(payload, "player", None)
        if not player or not player.guild:
            return

        await self.play_next(player, player.guild.id)

    @commands.command()
    async def join(self, ctx):
        if not await self._ensure_author_in_voice(ctx):
            return

        channel = ctx.author.voice.channel

        if ctx.voice_client:
            await ctx.voice_client.move_to(channel)

        else:
            await channel.connect(
                cls=wavelink.Player
            )

        await ctx.send(
            f"🎧 Miku masuk ke **{channel}** ✨"
        )

    @commands.command()
    async def leave(self, ctx):
        vc: wavelink.Player = ctx.voice_client

        if vc:
            await vc.disconnect()

            await ctx.send(
                "👋 Jaa nee~"
            )

    @commands.command()
    async def play(self, ctx, *, query):
        if not await self._ensure_author_in_voice(ctx):
            return

        player = ctx.voice_client or await ctx.author.voice.channel.connect(cls=wavelink.Player)

        loading = await ctx.send(
            embed=create_miku_embed(
                "🔎 Searching...",
                f"Miku sedang mencari:\n`{query}`",
            )
        )
        tracks = await wavelink.Playable.search(query, source=wavelink.TrackSource.YouTubeMusic)

        if not tracks:
            return await loading.edit(content="❌ Lagu tidak ditemukan.", embed=None)

        parsed = self._parse_search_result(tracks)
        search_tracks = parsed["tracks"]
        if not search_tracks:
            return await loading.edit(content="❌ Playlist kosong atau tidak dapat dibaca.", embed=None)

        if parsed["is_playlist"]:
            requester = ctx.author.mention
            playlist_name = parsed["name"]

            if player.playing or player.paused:
                added_count, skipped_count = self._append_tracks_to_queue(
                    ctx.guild.id,
                    search_tracks,
                    requester,
                )

                if added_count == 0:
                    return await loading.edit(
                        embed=create_miku_embed(
                            "📭 Queue Penuh",
                            f"Queue sudah mencapai batas **{MAX_QUEUE_SIZE}** lagu.",
                        )
                    )

                description = (
                    f"🎶 **{playlist_name}**\n"
                    f"✅ Ditambahkan: **{added_count}** lagu"
                )
                if skipped_count > 0:
                    description += f"\n⚠️ Dilewati karena batas queue: **{skipped_count}**"

                return await loading.edit(
                    embed=create_miku_embed("📜 Playlist Added To Queue", description)
                )

            first_track = search_tracks[0]
            self.current_song[ctx.guild.id] = self._make_song_entry(first_track, requester)

            remaining_tracks = search_tracks[1:]
            added_count, skipped_count = self._append_tracks_to_queue(
                ctx.guild.id,
                remaining_tracks,
                requester,
            )

            await self._start_track(player, ctx.guild.id, first_track, message=loading)

            description = (
                f"🎶 **{playlist_name}**\n"
                f"▶️ Sedang diputar: **{self._get_track_title(first_track)}**\n"
                f"📥 Masuk queue: **{added_count}** lagu"
            )
            if skipped_count > 0:
                description += f"\n⚠️ Dilewati karena batas queue: **{skipped_count}**"

            await ctx.send(embed=create_miku_embed("📜 Playlist Loaded", description))
            return

        track = search_tracks[0]
        song_entry = self._make_song_entry(track, ctx.author.mention)

        if player.playing or player.paused:
            queue = self._get_or_create_queue(ctx.guild.id)
            queue.append(song_entry)
            await loading.edit(
                embed=create_miku_embed(
                    "📜 Added To Queue",
                    f"🎵 **{self._get_track_title(track)}**",
                )
            )
            return

        self.current_song[ctx.guild.id] = song_entry
        await self._start_track(player, ctx.guild.id, track, message=loading)

    @commands.command(aliases=["np"])
    async def nowplaying(self, ctx):
        song = self.current_song.get(ctx.guild.id)

        if not song:
            return await ctx.send("🎵 Tidak ada lagu.")

        current = int(time.time() - self.song_start_time.get(ctx.guild.id, time.time()))

        track = song["track"]
        duration = self._get_track_duration(track)

        embed = self._build_now_playing_embed(
            track,
            song["requester"],
            current,
            duration,
        )

        await ctx.send(embed=embed)

    @commands.command()
    async def queue(self, ctx):
        guild_id = ctx.guild.id
        queue = self.music_queue.get(guild_id)

        if not queue:
            return await ctx.send("📭 Queue kosong~")

        total_pages = max(1, (len(queue) + QUEUE_PAGE_SIZE - 1) // QUEUE_PAGE_SIZE)
        embed = self._build_queue_embed(queue, page=0, total_pages=total_pages)
        try:
            if len(queue) <= QUEUE_PAGE_SIZE:
                message = await ctx.send(embed=embed)
                self.bot.loop.create_task(self._delete_message_after(message, QUEUE_VIEW_TIMEOUT))
                return

            view = QueuePaginationView(self, guild_id, ctx.author.id)
            view._update_button_states()
            message = await ctx.send(embed=embed, view=view)
            view.message = message
        except discord.HTTPException:
            await ctx.send("❌ Queue terlalu panjang untuk ditampilkan.")

    @commands.command()
    async def skip(self, ctx):
        vc: wavelink.Player = ctx.voice_client

        if vc:
            self.is_looping[ctx.guild.id] = False

            await vc.skip()

            await ctx.send(
                "⏭️ Lagu dilewati~"
            )

    @commands.command()
    async def pause(self, ctx):
        vc = await self._ensure_same_voice_channel(ctx)
        if not vc:
            return

        if vc.paused:
            return await ctx.send("⏸️ Musik sudah dijeda.")

        if not vc.playing:
            return await ctx.send("🎵 Tidak ada lagu yang sedang diputar.")

        await vc.pause(True)
        await ctx.send("⏸️ Musik dijeda~")

    @commands.command(aliases=["unpause"])
    async def resume(self, ctx):
        vc = await self._ensure_same_voice_channel(ctx)
        if not vc:
            return

        if not vc.paused:
            return await ctx.send("▶️ Musik tidak dalam kondisi jeda.")

        await vc.pause(False)
        await ctx.send("▶️ Musik dilanjutkan~")

    @commands.command()
    async def stop(self, ctx):
        vc: wavelink.Player = ctx.voice_client

        if vc:
            self._reset_guild_state(ctx.guild.id)

            vc.queue.clear()

            await vc.stop()

            await ctx.send(
                "⏹️ Musik dihentikan~"
            )

    @commands.command()
    async def loop(self, ctx):
        guild_id = ctx.guild.id

        self.is_looping[guild_id] = not self.is_looping.get(
            guild_id,
            False
        )

        if self.is_looping[guild_id]:
            await ctx.send(
                "🔁 Loop diaktifkan ✨"
            )

        else:
            await ctx.send(
                "➡️ Loop dimatikan."
            )

    @commands.command()
    async def volume(self, ctx, vol: int):
        if vol < 0 or vol > 100:
            return await ctx.send(
                "🔊 Volume 0 - 100"
            )

        vc: wavelink.Player = ctx.voice_client

        if vc:
            await vc.set_volume(vol)

            await ctx.send(
                f"🔊 Volume menjadi **{vol}%**"
            )


async def setup(bot):
    await bot.add_cog(Music(bot))
