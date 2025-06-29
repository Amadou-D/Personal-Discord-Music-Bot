import discord
from discord.ext import commands, tasks
import os
import asyncio
import yt_dlp
import tempfile
import shutil
import uuid
import subprocess
import sys
import re
import urllib.request
from dotenv import load_dotenv
from flask import Flask
from threading import Thread
import time
import aiohttp  # Make sure to import this
import socket  # For network diagnostics

# Add this: Check for PyNaCl, which is required for voice.
try:
    import nacl
except ImportError:
    print("PyNaCl is not installed, which is required for voice functionality.")
    print("Please install it with: pip install PyNaCl")
    sys.exit()

# Add this: Try to import pytube for alternative extraction
try:
    import pytube
    from pytube.exceptions import RegexMatchError, PytubeError
    PYTUBE_AVAILABLE = True
except ImportError:
    PYTUBE_AVAILABLE = False
    print("pytube not installed. To enable alternative extraction, install it with: pip install pytube")

# Create a web server to keep the bot alive (Not necessary if you are hosting the bot on a server)
app = Flask('')

@app.route('/')
def home():
    return "Bot is running!"

def run():
    app.run(host='0.0.0.0', port=8080)

def keep_alive():
    t = Thread(target=run)
    t.start()

def run_bot():
    load_dotenv()
    TOKEN = os.getenv('TOKEN')
    if not TOKEN:
        raise ValueError("No token provided. Please set the 'TOKEN' environment variable.")

    # Create temp directory for downloads
    temp_dir = os.path.join(tempfile.gettempdir(), "discord_bot_audio")
    os.makedirs(temp_dir, exist_ok=True)
    print(f"Using temp directory: {temp_dir}")

    # Clean up any old files in temp directory
    def cleanup_temp_files():
        try:
            for file in os.listdir(temp_dir):
                file_path = os.path.join(temp_dir, file)
                if os.path.isfile(file_path):
                    os.unlink(file_path)
        except Exception as e:
            print(f"Error cleaning temp directory: {e}")

    # Clean up on start
    cleanup_temp_files()

    intents = discord.Intents.default()
    intents.message_content = True
    intents.voice_states = True  # REQUIRED for voice state tracking
    client = commands.Bot(command_prefix=".", intents=intents)
    client.remove_command('help') # Remove default help command

    queues = {}
    currently_playing = {}  # Track currently playing songs
    youtube_base_url = 'https://www.youtube.com/'
    youtube_watch_url = youtube_base_url + 'watch?v='

    # List of regions to try if the default one fails.
    VOICE_REGIONS_FALLBACK = ['us-central', 'us-east', 'us-west', 'europe', 'brazil']

    # Path to ffmpeg executable
    ffmpeg_path = "C:\\ffmpeg\\bin\\ffmpeg.exe"  # Update this path to your ffmpeg executable

    # Enhanced ffmpeg options based on community suggestions
    ffmpeg_options = {
        # Strategy 1: Enhanced reconnection options for streaming
        'streaming': {
            'executable': ffmpeg_path,
            'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 10 -timeout 15000000',
            'options': '-vn -filter:a "volume=0.25"'
        },
        # Strategy 2: Basic streaming with minimal options
        'basic': {
            'executable': ffmpeg_path,
            'options': '-vn -filter:a "volume=0.25"'
        },
        # Strategy 3: For local file playback
        'local': {
            'executable': ffmpeg_path,
            'options': '-vn -filter:a "volume=0.25"'
        }
    }

    # Add this missing global variable at the top level (there's an error in the current code)
    voice_connect_cooldown = {}

    # Add this at the top with other mode variables
    compatibility_mode = {}  # Guild IDs that use compatibility mode

    # Add these new utility functions before @client.event functions
    async def safe_voice_connect(channel, timeout=10.0):
        """
        Connect to a voice channel with proper error handling and no automatic reconnects.
        This prevents the discord.py library from getting stuck in reconnect loops.
        """
        try:
            # Create connection options with reconnect disabled
            voice_client = await channel.connect(timeout=timeout, reconnect=False)
            return voice_client, None
        except asyncio.TimeoutError:
            return None, "Connection timed out. Discord voice servers might be having issues."
        except discord.ClientException as e:
            return None, f"Discord client error: {e}"
        except Exception as e:
            return None, f"Error connecting: {e}"

    @client.event
    async def on_ready():
        print(f'{client.user} is now jamming')
        print("---")
        print("INFO: If you experience voice connection errors (like 4006), your hosting environment may be blocking Discord's voice servers.")
        print("INFO: In such cases, use the '.compatibilitymode on' command in your server to switch to a file-based playback method.")
        print("---")
        check_voice_activity.start()

    @client.event
    async def on_voice_state_update(member, before, after):
        """Handles voice state changes to clean up resources."""
        # Check if the bot is the one who's voice state changed
        if member.id == client.user.id:
            # If the bot was disconnected from a channel
            if before.channel is not None and after.channel is None:
                guild_id = before.channel.guild.id
                print(f"Bot was disconnected from voice channel in guild {guild_id}.")
                # Clean up the queue for that guild
                if guild_id in queues:
                    queues[guild_id].clear()
                    print(f"Cleared queue for guild {guild_id}.")

    # Audio extraction utility using different strategies
    class AudioExtractor:
        # Itags known to work well with Discord ffmpeg
        AUDIO_ITAGS = [140, 141, 251, 250, 249, 139, 171, 18, 22]
        
        @staticmethod
        async def extract_with_pytube(url, ctx):
            """Extract audio using pytube and specific itags"""
            if not PYTUBE_AVAILABLE:
                await ctx.send("⚠️ pytube not available, using fallback method...")
                raise ImportError("pytube not installed")
                
            try:
                await ctx.send("🔍 Extracting audio stream with pytube...")
                
                # Extract video ID from the URL if it's a YouTube URL
                video_id = None
                if "youtube.com" in url:
                    video_id = url.split("v=")[-1].split("&")[0]
                elif "youtu.be" in url:
                    video_id = url.split("/")[-1].split("?")[0]
                
                if not video_id:
                    raise ValueError("Could not extract YouTube video ID")
                
                # Create YouTube object with modified approach to prevent 400 errors
                yt = None
                try:
                    # First try with default method
                    yt = pytube.YouTube(url)
                    title = yt.title
                except Exception as e:
                    print(f"Initial pytube error: {e}")
                    # Try with alternative method that adds headers and bypasses age restriction
                    try:
                        yt = pytube.YouTube(
                            url,
                            use_oauth=False,
                            allow_oauth_cache=True
                        )
                        title = yt.title
                    except Exception as e2:
                        print(f"Alternative pytube initialization failed: {e2}")
                        raise e2
                
                # Method 1: Use general stream selection to find audio
                try:
                    print("Trying general stream selection...")
                    
                    # First try to get audio-only streams sorted by quality
                    audio_streams = yt.streams.filter(only_audio=True).order_by('abr').desc()
                    if audio_streams:
                        chosen_stream = audio_streams.first()
                        if chosen_stream:
                            print(f"Found audio stream: {chosen_stream}")
                            audio_url = chosen_stream.url
                            return audio_url, title
                            

                    # If no audio streams, try getting any stream that we can extract audio from
                    all_streams = yt.streams.filter().order_by('resolution').desc()
                    if all_streams:
                        chosen_stream = all_streams.first()
                        if chosen_stream:
                            print(f"Found general stream: {chosen_stream}")
                            audio_url = chosen_stream.url
                            return audio_url, title
                            

                except Exception as e:
                    print(f"General stream selection failed: {e}")
                
                # Method 2: DASH streams (more reliable but may still get blocked)
                try:
                    print("Trying DASH streams...")
                    # Enable adaptive streams access that includes audio-only formats
                    streams = yt.streams.filter(adaptive=True).order_by('abr').desc()
                    for stream in streams:
                        if stream.includes_audio_track:
                            print(f"Using adaptive stream: {stream}")
                            return stream.url, title
                except Exception as e:
                    print(f"DASH stream approach failed: {e}")
                
                # Method 3: Try to use the native get_by_itag but without HTTP request
                print("Trying manual itag extraction...")
                for itag in AudioExtractor.AUDIO_ITAGS:
                    try:
                        stream = yt.streams.get_by_itag(itag)
                        if stream:
                            print(f"Found stream with itag {itag}")
                            return stream.url, title
                    except Exception as e:
                        print(f"Failed to get itag {itag}: {e}")
                
                raise Exception("No suitable audio stream found with pytube")
                    
            except Exception as e:
                print(f"pytube extraction failed: {e}")
                raise
        
        @staticmethod
        async def get_audio_url(url, ctx):
            """Extract audio URL using multiple strategies"""
            # Try direct download first - most reliable method
            try:
                return await AudioExtractor.download_directly(url, ctx)
            except Exception as e:
                print(f"Direct download failed: {e}")
                await ctx.send("Direct download failed, trying streaming methods...")
            
            # Continue with other strategies...
            try:
                # Strategy 1: Default extraction with specific format to avoid HLS streams
                ytdl = yt_dlp.YoutubeDL({
                    "format": "bestaudio[ext!=m3u8]/bestaudio/best",  # Avoid m3u8 (HLS) formats
                    "playlist_items": "1",
                    "extractor_args": {"youtube": {"player_client": ["web_safari"]}}
                })
                data = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ytdl.extract_info(url, download=False)
                )
                
                if 'entries' in data:
                    return data['entries'][0]['url'], data['entries'][0].get('title', 'Unknown')
                else:
                    return data['url'], data.get('title', 'Unknown')
                    
            except Exception as e:
                print(f"Strategy 1 failed: {e}")
                try:
                    # Strategy 2: Try with explicit format ids
                    ytdl = yt_dlp.YoutubeDL({
                        "format": "140/251/250/249/bestaudio/18/22",  # Direct format IDs to avoid HLS
                        "playlist_items": "1",
                        "extractor_args": {"youtube": {"player_client": ["web_safari", "web", "android"]}}
                    })
                    data = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: ytdl.extract_info(url, download=False)
                    )
                    
                    if 'entries' in data:
                        return data['entries'][0]['url'], data['entries'][0].get('title', 'Unknown')
                    else:
                        return data['url'], data.get('title', 'Unknown')
                        
                except Exception as e2:
                    print(f"Strategy 2 failed: {e2}")
                    await ctx.send("Having trouble extracting audio. Trying alternative method...")
                    
                    # Strategy 3: Fall back to downloading the audio
                    return await AudioExtractor.download_and_get_path(url, ctx)
        
        @staticmethod
        async def download_and_get_path(url, ctx):
            """Download audio to local file and return path"""
            try:
                # Generate unique filename
                unique_id = str(uuid.uuid4())
                output_file_base = os.path.join(temp_dir, unique_id)
                
                await ctx.send("⏳ Downloading audio file for more reliable playback...")
                
                # First try direct format download without postprocessing
                ydl_opts = {
                    'format': '140/18/251/bestaudio',  # Specific format IDs to avoid HLS
                    'outtmpl': output_file_base + ".mp3",  # Force .mp3 extension
                    'keepvideo': False,
                    'quiet': False,
                    'no_warnings': False,
                    'extractor_args': {"youtube": {"player_client": ["web_safari"]}}
                }
                
                # Download the file
                def download_audio():
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        info = ydl.extract_info(url, download=True)
                        if 'entries' in info:
                            info = info['entries'][0]
                        return info.get('title', 'Unknown')
                
                try:
                    title = await asyncio.get_event_loop().run_in_executor(None, download_audio)
                    output_file = output_file_base + ".mp3"
                    
                    if not os.path.exists(output_file) or os.path.getsize(output_file) < 1000:
                        raise Exception("First download attempt failed, trying ffmpeg conversion")
                except Exception as e:
                    print(f"First download method failed: {e}")
                    # Second attempt with ffmpeg conversion
                    ydl_opts = {
                        'format': 'bestaudio/best',
                        'outtmpl': output_file_base,
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                        'quiet': False,
                        'extractor_args': {"youtube": {"player_client": ["web_safari"]}}
                    }
                    
                    title = await asyncio.get_event_loop().run_in_executor(None, download_audio)
                    output_file = output_file_base + ".mp3"
                
                # Check for various possible file paths
                file_paths = [
                    output_file,
                    output_file_base + ".mp3.mp3",  # Handle double extension
                    output_file_base + ".m4a",
                    output_file_base + ".webm",
                    output_file_base + ".opus"
                ]
                
                found_file = None
                for file_path in file_paths:
                    if os.path.exists(file_path) and os.path.getsize(file_path) > 1000:  # At least 1KB
                        found_file = file_path
                        break
                        
                # If no file found, try glob pattern
                if not found_file:
                    import glob
                    files = glob.glob(f"{output_file_base}*")
                    for file in files:
                        if os.path.getsize(file) > 1000:  # At least 1KB
                            found_file = file
                            break
                        
                if found_file:
                    print(f"Successfully downloaded file: {found_file} ({os.path.getsize(found_file)} bytes)")
                    await ctx.send(f"✅ Download complete! ({os.path.getsize(found_file)/1024:.1f} KB)")
                    return found_file, title
                else:
                    raise FileNotFoundError(f"Downloaded file not found or too small for {url}")
                    
            except Exception as e:
                print(f"Download failed: {e}")
                await ctx.send(f"⚠️ Download failed: {str(e)[:100]}...")
                raise

        @staticmethod
        async def download_directly(url, ctx):
            """Use direct command line approach to download audio"""
            try:
                await ctx.send("🔄 Using direct download method...")
                
                # Generate unique filename
                unique_id = str(uuid.uuid4())
                output_file_base = os.path.join(temp_dir, unique_id)
                output_file = f"{output_file_base}.mp3"
                
                # Prepare youtube-dl/yt-dlp command with very basic options
                # This approach often works when the library methods fail
                cmd = [
                    'yt-dlp',  # Try to use yt-dlp command line tool
                    '--no-playlist',
                    '--extract-audio',
                    '--audio-format', 'mp3',
                    '--audio-quality', '128K',
                    '-o', output_file,
                    url
                ]
                
                await ctx.send("📥 Downloading audio directly...")
                
                # Run the command
                process = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE
                )
                
                stdout, stderr = await process.communicate()
                
                if process.returncode != 0:
                    # If yt-dlp fails, try youtube-dl as fallback
                    await ctx.send("⚠️ First download tool failed, trying alternative...")
                    cmd[0] = 'youtube-dl'  # Switch to youtube-dl
                    
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    
                    stdout, stderr = await process.communicate()
                    
                    if process.returncode != 0:
                        raise Exception(f"Command line download failed: {stderr.decode()}")
                
                # Check if file exists and is not empty
                if os.path.exists(output_file) and os.path.getsize(output_file) > 10000:
                    # Get title from filename or URL
                    if "youtube.com" in url or "youtu.be" in url:
                        # Try to extract video ID and get title
                        try:
                            video_id = None
                            if "youtube.com" in url:
                                video_id = url.split("v=")[-1].split("&")[0]
                            elif "youtu.be" in url:
                                video_id = url.split("/")[-1].split("?")[0]
                                
                            # Use offline method to get title if possible
                            title = f"YouTube Video ({video_id})"
                        except:
                            title = "YouTube Video"
                    else:
                        title = os.path.basename(url)
                    
                    await ctx.send(f"✅ Direct download successful ({os.path.getsize(output_file)/1024:.1f} KB)")
                    return output_file, title
                else:
                    raise FileNotFoundError(f"Downloaded file not found or too small")
                    
            except Exception as e:
                print(f"Direct download failed: {e}")
                raise

    async def resolve_link(ctx, link):
        """Resolves a link or search query into a playable URL and title."""
        # Handle short youtube links
        if link.startswith("https://youtu.be/"):
            video_id = link.split('/')[-1]
            link = youtube_watch_url + video_id

        # If it's not a full YouTube URL, treat it as a search query
        if youtube_base_url not in link:
            await ctx.send(f"🔍 Searching for: `{link}`")
            
            ytdl = yt_dlp.YoutubeDL({
                "format": "bestaudio/best",
                "default_search": "ytsearch",
                "noplaylist": True,
                "quiet": True,
                "extract_flat": True
            })
            
            try:
                data = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: ytdl.extract_info(f"ytsearch:{link}", download=False)
                )
                
                if not data or 'entries' not in data or not data['entries']:
                    await ctx.send("❌ No results found for your search.")
                    return None, None
                
                video_id = data['entries'][0]['id']
                title = data['entries'][0].get('title', 'Unknown')
                url = youtube_watch_url + video_id
                await ctx.send(f"✅ Found: {title}")
                return url, title
            except Exception as e:
                print(f"Search error: {e}")
                await ctx.send(f"❌ Error during search: {str(e)[:100]}...")
                return None, None
        
        # If it's already a URL, return it. Title will be fetched during audio extraction.
        return link, None

    # Safe audio player function with multiple fallback strategies
    async def play_audio(ctx, url, title=None):
        guild_id = ctx.guild.id
        voice_client = discord.utils.get(client.voice_clients, guild=ctx.guild)

        # Final check to ensure we are still connected before playing
        if not voice_client or not voice_client.is_connected():
            await ctx.send("❌ Lost voice connection before playback. Please try again.")
            if guild_id in queues:
                queues[guild_id].clear()
            return
        
        # Set up playback error counter
        if guild_id not in currently_playing:
            currently_playing[guild_id] = {"retries": 0}
        
        # First strategy - direct download and play
        try:
            # Get audio file path or URL
            audio_path_or_url, audio_title = await AudioExtractor.get_audio_url(url, ctx)
            title = title or audio_title
            
            # Check if we got a local file path
            is_local_file = os.path.isfile(audio_path_or_url) if isinstance(audio_path_or_url, str) else False
            
            # Custom error handler for better retry handling
            def play_callback(error):
                if error:
                    print(f"Playback error: {error}")
                    asyncio.run_coroutine_threadsafe(
                        handle_playback_error(ctx, url, title, error), 
                        client.loop
                    )
                else:
                    # Successful playback completion
                    print(f"Playback completed successfully for {title}")
                    asyncio.run_coroutine_threadsafe(play_next(ctx), client.loop)
            
            # For local files, use FFmpegPCMAudio directly
            if is_local_file:
                print(f"Playing local file: {audio_path_or_url}")
                # Use basic local playback options
                source = discord.FFmpegPCMAudio(
                    audio_path_or_url,
                    executable=ffmpeg_path,
                    options='-vn -filter:a "volume=0.25"'
                )
                
                # Custom callback to clean up file after playing
                def after_local_playing(error):
                    # Delete the temporary file
                    try:
                        if os.path.exists(audio_path_or_url):
                            os.unlink(audio_path_or_url)
                            print(f"Deleted file: {audio_path_or_url}")
                    except Exception as e:
                        print(f"Error deleting file: {e}")
                    
                    # Handle errors or play next song
                    if error:
                        print(f"Playback error: {error}")
                        asyncio.run_coroutine_threadsafe(play_next(ctx), client.loop)
                    else:
                        asyncio.run_coroutine_threadsafe(play_next(ctx), client.loop)
                
                # Apply volume control and play
                source = discord.PCMVolumeTransformer(source, volume=0.5)
                voice_client.play(source, after=after_local_playing)
                await ctx.send(f"▶️ Now playing: {title}")
            else:
                # For streaming URLs, consistently use FFmpegPCMAudio for stability
                print(f"Playing streaming URL: {audio_path_or_url[:100]}...")
                
                before_options = '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5'
                
                source = discord.FFmpegPCMAudio(
                    audio_path_or_url,
                    executable=ffmpeg_path,
                    before_options=before_options,
                    options='-vn -filter:a "volume=0.25"'
                )
                
                # Apply volume control
                source = discord.PCMVolumeTransformer(source, volume=0.5)
                voice_client.play(source, after=play_callback)
                await ctx.send(f"▶️ Now playing: {title}")
            
        except Exception as e:
            print(f"Error in play_audio: {e}")
            await ctx.send(f"❌ Error playing audio: {str(e)[:100]}...")
            await handle_playback_error(ctx, url, title, e)

    async def handle_playback_error(ctx, url, title, error):
        """Handle errors during playback by disconnecting to prevent loops."""
        guild_id = ctx.guild.id
        
        await ctx.send(
            f"❌ **A critical playback error occurred:** `{str(error)[:100]}`\n"
            "To prevent further issues, I am disconnecting from the voice channel. "
            "This is often caused by an unstable connection to Discord's voice servers. "
            "Please try again in a moment."
        )
        
        # Reset retry counter
        if guild_id in currently_playing:
            del currently_playing[guild_id]
        
        # Disconnect from voice to break any error loops
        voice_client = discord.utils.get(client.voice_clients, guild=ctx.guild)
        if voice_client and voice_client.is_connected():
            await voice_client.disconnect() # This will trigger on_voice_state_update to clear the queue

    async def play_next(ctx):
        """Play the next song in the queue if exists"""
        guild_id = ctx.guild.id
        # Compatibility mode has its own queue logic
        if guild_id in compatibility_mode and compatibility_mode[guild_id]:
            if guild_id in queues and queues[guild_id]:
                next_link = queues[guild_id].pop(0)
                await ctx.send("▶️ Processing next song in compatibility queue...")
                # This is a bit recursive, but it's the simplest way
                await play(ctx, link=next_link) 
            else:
                await ctx.send("✅ Compatibility queue finished.")
                if guild_id in currently_playing:
                    del currently_playing[guild_id]
            return

        voice_client = discord.utils.get(client.voice_clients, guild=ctx.guild)
        if not voice_client or not voice_client.is_connected() or voice_client.is_playing() or voice_client.is_paused():
            return

        try:
            if ctx.guild.id in queues and queues[ctx.guild.id]:
                if ctx.guild.id in currently_playing:
                    currently_playing[ctx.guild.id]["retries"] = 0
                
                next_link = queues[ctx.guild.id].pop(0)
                
                # Resolve link (in case it's a search query)
                url, title = await resolve_link(ctx, next_link)
                if url:
                    await play_audio(ctx, url, title=title)
            else:
                # Queue is empty, stay connected but reset play state
                if ctx.guild.id in currently_playing:
                    currently_playing[ctx.guild.id]["retries"] = 0
                
                if voice_client and voice_client.is_connected():
                    await ctx.send("Queue is empty. Add more songs with `.play [link/search]`")
                    await ctx.send("Bot will automatically disconnect after 5 minutes of inactivity.")
        except Exception as e:
            print(f"Error in play_next: {e}")

    @client.command(name="play")
    async def play(ctx, *, link):
        try:
            guild_id = ctx.guild.id
            # Check for compatibility mode
            if guild_id in compatibility_mode and compatibility_mode[guild_id]:
                await ctx.send("🔧 Using compatibility mode...")
                
                # In this mode, we don't join a voice channel. We just download and send the file.
                if not ctx.author.voice or not ctx.author.voice.channel:
                    await ctx.send("❌ You still need to be in a voice channel to use this command (so I know where to send messages).")
                    return

                # Initialize queue if needed
                if guild_id not in queues:
                    queues[guild_id] = []

                # If something is "playing", add to queue
                if guild_id in currently_playing and currently_playing[guild_id].get('is_playing'):
                    queues[guild_id].append(link)
                    await ctx.send(f"➕ Added to compatibility queue: `{link}`")
                    return

                # "Play" the song
                await ctx.send("📥 Downloading audio for compatibility mode...")
                try:
                    url, title = await resolve_link(ctx, link)
                    if not url:
                        return
                    
                    audio_path, file_title = await AudioExtractor.download_and_get_path(url, ctx)
                    title = title or file_title

                    await ctx.send(
                        "📱 **Compatibility Mode is ON.**\n"
                        "The bot **cannot** join your voice channel due to the network error.\n\n"
                        f"Instead, here is the audio file for **{title}**.\n"
                        "**⬇️ Please download the file below and play it on your computer or phone.**"
                    )

                    # Send the file
                    file_size_mb = os.path.getsize(audio_path) / (1024 * 1024)
                    if file_size_mb > 8.0:
                        await ctx.send(f"⚠️ Audio file is too large ({file_size_mb:.1f}MB) to upload. Please try a shorter song.")
                        os.unlink(audio_path)
                        # Mark as not playing and try next
                        if guild_id in currently_playing:
                            del currently_playing[guild_id]
                        await play_next(ctx)
                        return

                    await ctx.send(file=discord.File(audio_path))
                    os.unlink(audio_path) # Delete after sending

                    # Mark as playing
                    currently_playing[guild_id] = {'is_playing': True, 'title': title}
                    
                except Exception as e:
                    await ctx.send(f"❌ Compatibility mode failed: {str(e)[:100]}...")
                    if guild_id in currently_playing:
                        del currently_playing[guild_id]
                
                return # End of compatibility mode logic

            # Ensure user is in a voice channel
            if not ctx.author.voice or not ctx.author.voice.channel:
                await ctx.send("❌ You need to be in a voice channel to use this command.")
                return

            voice_channel = ctx.author.voice.channel
            voice_client = discord.utils.get(client.voice_clients, guild=ctx.guild)

            # Circuit breaker: prevent rapid reconnect attempts
            cooldown = voice_connect_cooldown.get(ctx.guild.id, 0)
            now = asyncio.get_event_loop().time()
            if cooldown > now:
                remaining = int(cooldown - now)
                await ctx.send(f"⚠️ Voice connection cooldown active. Please wait {remaining} seconds before trying again.")
                return

            # Handle connecting and moving channels
            if voice_client and voice_client.is_connected():
                if voice_client.channel != voice_channel:
                    await voice_client.move_to(voice_channel)
                    await ctx.send(f"➡️ Moved to {voice_channel.name}")
            else:
                # Check permissions before connecting
                perms = voice_channel.permissions_for(ctx.guild.me)
                if not perms.connect:
                    await ctx.send(f"❌ I don't have permission to **connect** to `{voice_channel.name}`. Please check my role permissions.")
                    return
                if not perms.speak:
                    await ctx.send(f"❌ I don't have permission to **speak** in `{voice_channel.name}`. Please check my role permissions.")
                    return

                # Clear any existing voice clients for this guild
                existing_voice = discord.utils.get(client.voice_clients, guild=ctx.guild)
                if existing_voice:
                    try:
                        await existing_voice.disconnect(force=True)
                        await asyncio.sleep(1)  # Give Discord time to register the disconnect
                    except:
                        pass
                
                # Attempt connection with our safe method (no reconnect loop)
                await ctx.send(f"🔄 Connecting to {voice_channel.name}...")
                voice_client, error = await safe_voice_connect(voice_channel, timeout=10.0)
                
                if error:
                    # --- Automatic Region Fallback Logic ---
                    await ctx.send(f"⚠️ Initial connection failed: `{error}`. Attempting to switch voice regions...")
                    
                    if not voice_channel.permissions_for(ctx.guild.me).manage_channels:
                        await ctx.send("❌ I can't automatically switch regions because I lack the **Manage Channels** permission.")
                    else:
                        original_region = voice_channel.rtc_region
                        for region_name in VOICE_REGIONS_FALLBACK:
                            await ctx.send(f"🔄 Trying region: `{region_name}`...")
                            try:
                                await voice_channel.edit(rtc_region=region_name)
                                await asyncio.sleep(1.5)

                                # Disconnect any lingering failed connections before retrying
                                lingering_vc = discord.utils.get(client.voice_clients, guild=ctx.guild)
                                if lingering_vc:
                                    await lingering_vc.disconnect(force=True)
                                    await asyncio.sleep(1)

                                voice_client, error = await safe_voice_connect(voice_channel, timeout=10.0)
                                if not error:
                                    await ctx.send(f"✅ Successfully connected in `{region_name}` region!")
                                    break  # Success!
                                else:
                                    await ctx.send(f"⚠️ Connection to `{region_name}` failed.")
                            except Exception as e:
                                await ctx.send(f"⚠️ Could not switch to or connect in `{region_name}` region.")
                                print(f"Region switch error: {e}")
                        
                        if error: # If all fallbacks failed
                            try: # Try to set region back to original
                                await voice_channel.edit(rtc_region=original_region)
                            except: pass
                
                if error:
                    # Set a 30-second cooldown on connection attempts for this guild
                    voice_connect_cooldown[ctx.guild.id] = asyncio.get_event_loop().time() + 30
                        
                    await ctx.send(
                        f"❌ **Connection failed after trying multiple regions.**\n"
                        "This is a persistent network problem. The final solution is to use compatibility mode:\n"
                        "`.compatibilitymode on`"
                    )
                    return
                else:
                    await ctx.send(f"👋 Joined {voice_channel.name}")

            # Double-check connection and cooldown
            if not voice_client or not voice_client.is_connected():
                voice_connect_cooldown[ctx.guild.id] = asyncio.get_event_loop().time() + 30
                await ctx.send("❌ Voice connection lost immediately after connecting. This suggests a network issue.")
                return

            # Initialize queue if needed
            if ctx.guild.id not in queues:
                queues[ctx.guild.id] = []

            # Add to queue if already playing or paused
            if voice_client.is_playing() or voice_client.is_paused():
                queues[ctx.guild.id].append(link)
                await ctx.send(f"➕ Added to queue: `{link}`")
                return

            # Resolve the link or search query
            url, title = await resolve_link(ctx, link)
            if not url:
                return  # Error message was already sent

            # Now play the audio
            await play_audio(ctx, url, title=title)
            
        except Exception as e:
            print(f"Error in play command: {e}")
            await ctx.send(f'❌ An unexpected error occurred: {str(e)[:100]}...')

    @client.command(name="clear_queue")
    async def clear_queue(ctx):
        if ctx.guild.id in queues:
            queues[ctx.guild.id].clear()
            await ctx.send("🗑️ Queue cleared!")
        else:
            await ctx.send("ℹ️ There is no queue to clear")

    @client.command(name="queue")
    async def view_queue(ctx):
        """View the current queue of songs"""
        if ctx.guild.id not in queues or not queues[ctx.guild.id]:
            await ctx.send("ℹ️ The queue is empty.")
            return
            
        # Format the queue list
        queue_msg = "📋 **Current Queue:**\n"
        for i, link in enumerate(queues[ctx.guild.id], 1):
            if youtube_base_url in link:
                video_id = link.split('=')[-1]
                queue_msg += f"{i}. https://youtu.be/{video_id}\n"
            else:
                queue_msg += f"{i}. {link}\n"
                
        # Truncate if too long
        if len(queue_msg) > 1900:
            queue_msg = queue_msg[:1900] + "...\n(Queue too long to display fully)"
            
        await ctx.send(queue_msg)

    @client.command(name="pause")
    async def pause(ctx):
        guild_id = ctx.guild.id
        if guild_id in compatibility_mode and compatibility_mode[guild_id]:
            await ctx.send("ℹ️ Pause is not available in compatibility mode.")
            return
        voice_client = discord.utils.get(client.voice_clients, guild=ctx.guild)
        try:
            if voice_client and voice_client.is_playing():
                voice_client.pause()
                await ctx.send("⏸️ Paused playback.")
            else:
                await ctx.send("ℹ️ Nothing is playing right now.")
        except Exception as e:
            print(f"Error in pause: {e}")
            await ctx.send("❌ Error pausing playback.")

    @client.command(name="resume")
    async def resume(ctx):
        guild_id = ctx.guild.id
        if guild_id in compatibility_mode and compatibility_mode[guild_id]:
            await ctx.send("ℹ️ Resume is not available in compatibility mode.")
            return
        voice_client = discord.utils.get(client.voice_clients, guild=ctx.guild)
        try:
            if voice_client and voice_client.is_paused():
                voice_client.resume()
                await ctx.send("▶️ Resumed playback.")
            else:
                await ctx.send("ℹ️ Nothing is paused right now.")
        except Exception as e:
            print(f"Error in resume: {e}")
            await ctx.send("❌ Error resuming playback.")

    @client.command(name="stop")
    async def stop(ctx):
        guild_id = ctx.guild.id
        if guild_id in compatibility_mode and compatibility_mode[guild_id]:
            if guild_id in queues:
                queues[guild_id].clear()
            if guild_id in currently_playing:
                del currently_playing[guild_id]
            await ctx.send("⏹️ Stopped and cleared compatibility queue.")
            return
        voice_client = discord.utils.get(client.voice_clients, guild=ctx.guild)
        try:
            if voice_client and (voice_client.is_playing() or voice_client.is_paused()):
                if ctx.guild.id in queues:
                    queues[ctx.guild.id].clear()
                voice_client.stop()
                await ctx.send("⏹️ Stopped playback and cleared the queue.")
            else:
                await ctx.send("ℹ️ Nothing is playing right now.")
        except Exception as e:
            print(f"Error in stop: {e}")
            await ctx.send("❌ Error stopping playback.")

    @client.command(name="leave")
    async def leave(ctx):
        guild_id = ctx.guild.id
        if guild_id in compatibility_mode and compatibility_mode[guild_id]:
            if guild_id in queues:
                queues[guild_id].clear()
            if guild_id in currently_playing:
                del currently_playing[guild_id]
            await ctx.send("👋 Cleared compatibility queue. I was never in a voice channel.")
            return
        voice_client = discord.utils.get(client.voice_clients, guild=ctx.guild)
        try:
            if voice_client and voice_client.is_connected():
                if ctx.guild.id in queues:
                    queues[ctx.guild.id].clear()
                await voice_client.disconnect()
                await ctx.send("👋 Disconnected from voice channel.")
            else:
                await ctx.send("ℹ️ I'm not connected to a voice channel.")
        except Exception as e:
            print(f"Error in leave: {e}")
            await ctx.send(f"❌ Error disconnecting: {str(e)[:100]}...")

    @client.command(name="skip")
    async def skip(ctx):
        guild_id = ctx.guild.id
        if guild_id in compatibility_mode and compatibility_mode[guild_id]:
            await ctx.send("⏭️ Skipped compatibility track.")
            if guild_id in currently_playing:
                del currently_playing[guild_id]
            await play_next(ctx)
            return
        voice_client = discord.utils.get(client.voice_clients, guild=ctx.guild)
        try:
            if voice_client and voice_client.is_playing():
                voice_client.stop()
                await ctx.send("⏭️ Skipped the current song.")
                # The 'after' callback from the original play call will trigger play_next
            else:
                await ctx.send("ℹ️ Nothing is playing right now.")
        except Exception as e:
            print(f"Error skipping the song: {e}")
            await ctx.send('❌ Error skipping the song.')

    @client.command(name="ping")
    async def ping(ctx):
        """Checks the bot's latency to Discord's gateway."""
        latency = client.latency * 1000  # Convert to milliseconds
        await ctx.send(f"Pong! 🏓\nGateway Latency: `{latency:.2f}ms`")

    @client.command(name="help")
    async def help_command(ctx):
        """Shows this help message."""
        embed = discord.Embed(
            title="Bot Help & Instructions",
            description="Here's how to use the music bot.",
            color=discord.Color.blue()
        )

        embed.add_field(
            name="🎵 Core Commands",
            value="`.play <song name or URL>`: Plays a song or adds it to the queue.\n"
                  "`.skip`: Skips the current song.\n"
                  "`.stop`: Stops playback and clears the queue.\n"
                  "`.leave`: Disconnects the bot from the voice channel.\n"
                  "`.queue`: Shows the current song queue.",
            inline=False
        )

        embed.add_field(
            name="⚙️ Modes & Utilities",
            value="`.status`: Shows the current mode of the bot.\n"
                  "`.compatibilitymode [on/off]`: Toggles compatibility mode.\n"
                  "`.ping`: Checks the bot's latency.\n"
                  "`.diagnostics`: Runs network diagnostics.",
            inline=False
        )

        embed.add_field(
            name="⚠️ How to use Compatibility Mode",
            value="If the bot fails to join voice chat, your network is likely the cause. This mode is the solution.\n\n"
                  "**1. Turn it on:**\n"
                  "` .compatibilitymode on `\n\n"
                  "**2. Play a song:**\n"
                  "` .play <song name> `\n\n"
                  "The bot **WILL NOT** join the voice channel. It will send an MP3 file in the chat for **you to download and play on your own device**.",
            inline=False
        )
        
        embed.set_footer(text="This bot is designed to be simple and robust.")
        await ctx.send(embed=embed)

    @client.command(name="status")
    async def status(ctx):
        """Shows the current operational mode of the bot for this server."""
        guild_id = ctx.guild.id
        
        comp_mode_status = "✅ ON" if guild_id in compatibility_mode and compatibility_mode[guild_id] else "❌ OFF"
        
        embed = discord.Embed(
            title="Bot Status",
            description=f"Here is the current configuration for **{ctx.guild.name}**.",
            color=discord.Color.green() if "ON" in comp_mode_status else discord.Color.orange()
        )
        
        embed.add_field(
            name="Compatibility Mode",
            value=f"**{comp_mode_status}**\n*If ON, the bot sends audio as files.*",
            inline=False
        )
        
        embed.set_footer(text="Use '.compatibilitymode on' if you have connection problems.")
        
        await ctx.send(embed=embed)

    @client.command(name="compatibilitymode")
    async def compatibility_mode_cmd(ctx, mode=None):
        """Activates compatibility mode as an absolute last resort.
        Usage: .compatibilitymode [on/off]
        This mode avoids voice channel connection entirely."""
        guild_id = ctx.guild.id
        
        # Show current status if no mode provided
        if mode is None:
            status = "enabled" if guild_id in compatibility_mode and compatibility_mode[guild_id] else "disabled"
            await ctx.send(f"Compatibility mode is currently **{status}** for this server.")
            return
            
        # Set mode based on argument
        if mode.lower() in ["on", "enable", "true", "1", "yes"]:
            compatibility_mode[guild_id] = True
            # Clear any cooldowns
            if guild_id in voice_connect_cooldown:
                del voice_connect_cooldown[guild_id]
                
            await ctx.send(
                "⚠️ **COMPATIBILITY MODE ENABLED**\n"
                "The bot will **NO LONGER** attempt to join voice channels due to network errors.\n"
                "It will now download songs and send them as files in this chat for you to play on your own device."
            )
        elif mode.lower() in ["off", "disable", "false", "0", "no"]:
            compatibility_mode[guild_id] = False
            await ctx.send("✅ Compatibility mode **disabled**.")
        else:
            await ctx.send("❌ Invalid option. Use 'on' or 'off'.")
    
    @client.command(name="diagnostics")
    async def diagnostics(ctx):
        """Run network and permission diagnostics to help troubleshoot voice issues."""
        try:
            # Gateway latency check
            latency = client.latency * 1000  # Convert to milliseconds
            latency_status = "✅ Good" if latency < 200 else "⚠️ High" if latency < 500 else "❌ Poor"
            
            # Permission check
            perms_status = "N/A (Not in a voice channel)"
            voice_perms = []
            channel_region = "N/A"
            if ctx.author.voice and ctx.author.voice.channel:
                channel = ctx.author.voice.channel
                channel_region = str(channel.rtc_region) if channel.rtc_region else "Automatic"
                perms = channel.permissions_for(ctx.guild.me)
                voice_perms = [
                    f"Connect: {'✅' if perms.connect else '❌'}",
                    f"Speak: {'✅' if perms.speak else '❌'}",
                    f"Priority Speaker: {'✅' if perms.priority_speaker else '❌'}"
                ]
                perms_status = "✅ All permissions" if perms.connect and perms.speak else "❌ Missing permissions"
            
            # Voice client status
            voice_client = discord.utils.get(client.voice_clients, guild=ctx.guild)
            voice_status = "❌ Not connected"
            if voice_client:
                if voice_client.is_connected():
                    voice_status = "✅ Connected"
                    if voice_client.is_playing():
                        voice_status += " (Playing)"
                    elif voice_client.is_paused():
                        voice_status += " (Paused)"
                else:
                    voice_status = "⚠️ Client exists but not connected"
            
            # External connectivity test
            try:
                # Test connection to Discord's voice gateway
                async with aiohttp.ClientSession() as session:
                    start_time = time.time()
                    async with session.get('https://discord.media', timeout=5) as resp:
                        media_latency = (time.time() - start_time) * 1000
                        media_status = f"✅ {media_latency:.0f}ms" if media_latency < 300 else f"⚠️ {media_latency:.0f}ms (High)"
            except Exception as e:
                media_status = f"❌ Failed: {str(e)[:50]}..."
                
            # UDP connectivity test
            udp_status = "Not tested"
            try:
                # Test UDP connectivity by trying to send a single packet
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(1)
                # Try to send a UDP packet to Discord's voice servers
                sock.sendto(b"TEST", ("discord.media", 50000))
                try:
                    # We don't expect a response, so if we get here, UDP sending worked
                    udp_status = "✅ UDP sending appears to work"
                except socket.timeout:
                    # This is actually expected since Discord won't respond
                    udp_status = "✅ UDP sending appears to work"
                sock.close()
            except Exception as e:
                udp_status = f"❌ UDP test failed: {str(e)[:50]}..."

            # Assemble diagnostic info
            info = [
                f"**Gateway Latency:** {latency:.2f}ms ({latency_status})",
                f"**Discord Media Latency:** {media_status}",
                f"**UDP Connectivity:** {udp_status}",
                f"**Voice Client Status:** {voice_status}",
                f"**Current Voice Region:** {channel_region}",
                f"**Permission Status:** {perms_status}",
                f"**Voice Permissions:**\n" + "\n".join(voice_perms) if voice_perms else "",
                f"**Compatibility Mode:** {'Enabled' if ctx.guild.id in compatibility_mode and compatibility_mode[ctx.guild.id] else 'Disabled'}",
                f"**Python Version:** {sys.version.split()[0]}",
                f"**Discord.py Version:** {discord.__version__}",
                f"**Platform:** {sys.platform}"
            ]
            
            embed = discord.Embed(
                title="Bot Diagnostics",
                description="\n\n".join(info),
                color=discord.Color.blue()
            )
            
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"Error running diagnostics: {e}")

    @tasks.loop(seconds=300)  # Check every 5 minutes
    async def check_voice_activity():
        """Check for inactive voice connections and disconnect if inactive for too long"""
        try:
            for vc in client.voice_clients:
                # If the bot is playing, it's not inactive
                if vc.is_playing():
                    continue
                
                # If the bot is alone in the channel, disconnect
                if len(vc.channel.members) == 1:
                    print(f"Bot is alone in {vc.channel}. Disconnecting.")
                    if vc.guild.id in queues:
                        queues[vc.guild.id].clear()
                    await vc.disconnect()
        except Exception as e:
            print(f"Error in check_voice_activity: {e}")

    client.run(TOKEN)

# Run the bot
keep_alive()
run_bot()