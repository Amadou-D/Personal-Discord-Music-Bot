🎵 Discord Music Bot

A Discord music bot that plays YouTube videos, including playlists, using your own Discord bot token and YouTube cookies for better compatibility.
 Setup
1. Get a Discord Bot Token

You'll need your own bot token to run this bot. Follow the official Discord guide to create and configure a bot:
🔗 Discord Developer Docs - https://discord.com/developers/docs/quick-start/getting-started

2. Obtain YouTube Cookies (Optional but Recommended)

Some videos require authentication to be played properly. To avoid restrictions, you can provide YouTube cookies:

    Export cookies from your web browser.
    Use cookies from an incognito session (logged in).
    Read more here: (https://github.com/yt-dlp/yt-dlp/wiki/FAQ) 

3. Install Dependencies

Make sure you have Node.js installed, then run:

npm install

4. Configure the Bot

Create a .env file in the project directory and add:

DISCORD_TOKEN=your-bot-token-here
YOUTUBE_COOKIES=your-cookie-string-here

5. Run the Bot
    Check Your Project Files:
        Make sure you have the following:
            main.py (your bot script).
            .env file (with your bot token).
            requirements.txt (optional, if you have a list of dependencies).
        Your .env file should contain the line:

    DISCORD_TOKEN=your-bot-token-here

Install Python Dependencies:

    Open a terminal in your project directory.
    Install all necessary libraries by running:

pip install -r requirements.txt

If you don't have a requirements.txt, you can install the core libraries directly:

    pip install discord.py python-dotenv

Run main.py:

    Ensure your terminal/command prompt is in the directory where main.py is located.
    Run the bot using the following command:

python main.py


✅ Supports YouTube videos & playlists
✅ Plays high-quality audio in voice channels
✅ Uses cookies to bypass restrictions
✅ Easy setup with environment variables
🛠 Troubleshooting

    Bot not joining the voice channel? Ensure it has the correct permissions.
    Songs not playing? Check if YouTube cookies are required.
    Still having issues? Open an issue or check the logs for errors.

Let me know if you need any edits! - Amadou

