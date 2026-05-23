import asyncio
import os
import random
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import discord
from discord.ext import commands
from dotenv import load_dotenv
import wavelink

load_dotenv()
TOKEN = os.getenv("DISCORD_TOKEN")
LAVALINK_URI = os.getenv("LAVALINK_URI", "http://127.0.0.1:2333")
LAVALINK_PASSWORD = os.getenv("LAVALINK_PASSWORD", "miku_password")
HEALTHCHECK_PORT = int(os.getenv("PORT", "10000"))


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/health":
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')

    def log_message(self, format, *_args):
        return


def start_healthcheck_server():
    server = HTTPServer(("0.0.0.0", HEALTHCHECK_PORT), HealthHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"🌐 Healthcheck server ready on :{HEALTHCHECK_PORT}/health")
    return server

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(
    command_prefix='!',
    intents=intents,
    help_command=None
)

_lavalink_connect_lock = asyncio.Lock()


async def connect_lavalink(max_attempts=30, delay_seconds=2):
    async with _lavalink_connect_lock:
        if wavelink.Pool.nodes:
            return True

        for attempt in range(1, max_attempts + 1):
            try:
                node = wavelink.Node(
                    uri=LAVALINK_URI,
                    password=LAVALINK_PASSWORD,
                )
                await wavelink.Pool.connect(nodes=[node], client=bot)
                print("🎶 Miku connected to Lavalink!")
                return True
            except Exception as error:
                print(
                    f"❌ Lavalink connect attempt {attempt}/{max_attempts} failed: {error}"
                )
                if attempt < max_attempts:
                    await asyncio.sleep(delay_seconds)

        print("❌ Lavalink connection failed after retries.")
        return False


async def lavalink_reconnect_loop():
    while True:
        if not wavelink.Pool.nodes:
            await connect_lavalink(max_attempts=5, delay_seconds=3)
        await asyncio.sleep(15)

@bot.event
async def on_ready():
    print(f"💙 Logged in as {bot.user}")
    await connect_lavalink(max_attempts=30, delay_seconds=2)

    if getattr(bot, "_lavalink_reconnector", None) is None:
        bot._lavalink_reconnector = asyncio.create_task(lavalink_reconnect_loop())

@bot.command()
async def halo(ctx):
    miku_quotes = [
        "Miku siap bernyanyi untukmu~ 🎶",
        "Hari ini juga semangat yaa! ✨",
        "La la la~ ada lagu request? 💙",
        "Miku online dan siap membantu! 🎤",
        "Jangan lupa senyum hari ini yaa~ 🌸"
    ]

    embed = discord.Embed(
        title="🎵 Haii semuanya~",
        description=f"Konnichiwa {ctx.author.mention} 💙\nAku Hatsune Miku virtual bot yang siap menemanimu~",
        color=0x39C5BB
    )

    embed.add_field(
        name="✨ Pesan Miku",
        value=random.choice(miku_quotes),
        inline=False
    )

    embed.add_field(
        name="🎶 Prefix",
        value="Gunakan `!help` untuk melihat command yaa~",
        inline=False
    )

    embed.set_thumbnail(
        url="https://i.imgur.com/RAZggjC.png"
    )

    embed.set_footer(
        text="ミク ミク ビーム ✨"
    )

    await ctx.send(embed=embed)

@bot.command()
async def help(ctx):
    embed = discord.Embed(
        title="🎤 Daftar Perintah Miku~",
        description="Konnichiwa! Ini daftar command Miku untuk music dan voice control 💙",
        color=0x39C5BB
    )

    embed.add_field(
        name="`!join` / `!leave`",
        value="Masuk ke voice channel kamu atau keluar dari voice channel.",
        inline=False
    )
    embed.add_field(
        name="`!play [judul/link]`",
        value="Putar lagu dari YouTube/YouTube Music. Link playlist akan dimuat otomatis (maks queue 100).",
        inline=False
    )
    embed.add_field(
        name="`!pause` / `!resume` (`!unpause`)",
        value="Jeda atau lanjutkan lagu. Kamu harus berada di VC yang sama dengan bot.",
        inline=False
    )
    embed.add_field(
        name="`!skip` / `!stop`",
        value="Lewati lagu saat ini atau hentikan musik dan bersihkan queue.",
        inline=False
    )
    embed.add_field(
        name="`!queue`",
        value="Lihat antrean lagu dengan tombol Prev/Next. Pesan queue auto-delete setelah 30 detik.",
        inline=False
    )
    embed.add_field(
        name="`!nowplaying` (`!np`)",
        value="Tampilkan lagu yang sedang diputar beserta progress bar.",
        inline=False
    )
    embed.add_field(
        name="`!loop` / `!volume [0-100]`",
        value="Aktif/nonaktif loop lagu saat ini dan atur volume bot.",
        inline=False
    )
    embed.add_field(
        name="`!halo`",
        value="Sapa Miku dan lihat pesan random harian ✨",
        inline=False
    )

    embed.set_thumbnail(url="https://i.imgur.com/RAZggjC.png")
    embed.set_footer(text="Gunakan prefix '!' yaa~ Contoh: !play hatsune miku world is mine")

    await ctx.send(embed=embed)

# Fungsi untuk memuat fitur dari folder cogs
async def main():
    if not TOKEN:
        raise RuntimeError("DISCORD_TOKEN belum di-set. Isi env DISCORD_TOKEN terlebih dahulu.")

    start_healthcheck_server()

    # Memuat file cogs/music.py
    await bot.load_extension('cogs.music')
    
    # Jalankan bot
    await bot.start(TOKEN)

# Menjalankan fungsi utama
if __name__ == '__main__':
    asyncio.run(main())
