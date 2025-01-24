import discord
from discord.ext import commands
import os
import asyncio
import yt_dlp
from dotenv import load_dotenv
import urllib.parse, urllib.request, re

def run_bot():
    load_dotenv()
    TOKEN = os.getenv('TOKEN')
    if not TOKEN:
        raise ValueError("No token provided. Please set the 'TOKEN' environment variable.")

    intents = discord.Intents.default()
    intents.message_content = True
    client = commands.Bot(command_prefix=".", intents=intents)

    queues = {}
    voice_clients = {}
    youtube_base_url = 'https://www.youtube.com/'
    youtube_results_url = youtube_base_url + 'results?'
    youtube_watch_url = youtube_base_url + 'watch?v='
    yt_dl_options = {"format": "bestaudio/best"}
    ytdl = yt_dlp.YoutubeDL(yt_dl_options)

    # Explicitly specify the path to the ffmpeg executable
    ffmpeg_path = "C:/ffmpeg/bin/ffmpeg.exe"  # Update this path to your ffmpeg executable

    ffmpeg_options = {
        'executable': ffmpeg_path,  # Use the explicit path to ffmpeg
        'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
        'options': '-vn -filter:a "volume=0.25"'
    }

    @client.event
    async def on_ready():
        print(f'{client.user} is now jamming')

    async def play_next(ctx):
        if queues[ctx.guild.id]:
            link = queues[ctx.guild.id].pop(0)
            await play(ctx, link=link)

    @client.command(name="play")
    async def play(ctx, *, link):
        try:
            if ctx.guild.id not in voice_clients or not voice_clients[ctx.guild.id].is_connected():
                voice_client = await ctx.author.voice.channel.connect()
                voice_clients[voice_client.guild.id] = voice_client
            else:
                voice_client = voice_clients[ctx.guild.id]
        except Exception as e:
            print(f"Error connecting to voice channel: {e}")
            await ctx.send("There was an error connecting to the voice channel.")
            return

        if ctx.guild.id not in queues:
            queues[ctx.guild.id] = []

        if voice_clients[ctx.guild.id].is_playing():
            queues[ctx.guild.id].append(link)
            await ctx.send("Added to queue!")
            return

        try:
            if youtube_base_url not in link:
                query_string = urllib.parse.urlencode({'search_query': link})
                content = urllib.request.urlopen(youtube_results_url + query_string)
                search_results = re.findall(r'/watch\?v=(.{11})', content.read().decode())
                
                if not search_results:
                    await ctx.send("No results found for the query.")
                    return

                link = youtube_watch_url + search_results[0]

            print(f"Processing link: {link}")

            loop = asyncio.get_event_loop()
            data = await loop.run_in_executor(None, lambda: ytdl.extract_info(link, download=False))

            song = data['url']
            print(f"Playing song URL: {song}")
            player = discord.FFmpegOpusAudio(song, **ffmpeg_options)

            voice_clients[ctx.guild.id].play(player, after=lambda e: asyncio.run_coroutine_threadsafe(play_next(ctx), client.loop))
            await ctx.send(f'Now playing: {data["title"]}')
        except discord.errors.ClientException as e:
            print(f"Error playing the song: {e}")
            if "Already playing audio" in str(e):
                queues[ctx.guild.id].append(link)
                await ctx.send("Added to queue!")
            else:
                await ctx.send('There was an error playing the song.')
        except Exception as e:
            print(f"Error playing the song: {e}")
            await ctx.send('There was an error playing the song.')

    @client.command(name="clear_queue")
    async def clear_queue(ctx):
        if ctx.guild.id in queues:
            queues[ctx.guild.id].clear()
            await ctx.send("Queue cleared!")
        else:
            await ctx.send("There is no queue to clear")

    @client.command(name="pause")
    async def pause(ctx):
        try:
            voice_clients[ctx.guild.id].pause()
        except Exception as e:
            print(e)

    @client.command(name="resume")
    async def resume(ctx):
        try:
            voice_clients[ctx.guild.id].resume()
        except Exception as e:
            print(e)

    @client.command(name="stop")
    async def stop(ctx):
        try:
            voice_clients[ctx.guild.id].stop()
            await voice_clients[ctx.guild.id].disconnect()
            del voice_clients[ctx.guild.id]
        except Exception as e:
            print(e)

    @client.command(name="skip")
    async def skip(ctx):
        try:
            if ctx.guild.id in voice_clients and voice_clients[ctx.guild.id].is_playing():
                voice_clients[ctx.guild.id].stop()
                await ctx.send("Skipped the current song.")
            else:
                await ctx.send("No song is currently playing.")
        except Exception as e:
            print(f"Error skipping the song: {e}")
            await ctx.send('There was an error skipping the song.')

    client.run(TOKEN)

# Run the bot
run_bot()