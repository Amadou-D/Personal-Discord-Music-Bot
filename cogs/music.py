import discord
from discord.ext import commands
import yt_dlp

class Music(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def play(self, ctx, *, url):
        """Plays a song from a URL (e.g., YouTube)"""
        
        YDL_OPTIONS = {
            'format': 'bestaudio/best',
            'noplaylist': True,
            'quiet': True,
            'default_search': 'auto',
        }
        FFMPEG_OPTIONS = {
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
            'options': '-vn',
        }

        voice_channel = ctx.author.voice.channel
        if not voice_channel:
            return await ctx.send("You are not connected to a voice channel.")

        if not ctx.voice_client:
            await voice_channel.connect()
        
        ctx.voice_client.stop()

        with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
            info = ydl.extract_info(url, download=False)
            audio_url = info['url']
            source = discord.FFmpegPCMAudio(audio_url, **FFMPEG_OPTIONS)
            
        ctx.voice_client.play(source, after=lambda e: print(f'Player error: {e}') if e else None)
        await ctx.send(f'Now playing: {info["title"]}')

async def setup(bot):
    await bot.add_cog(Music(bot))
