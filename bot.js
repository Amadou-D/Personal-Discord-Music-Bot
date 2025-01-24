const { Client, GatewayIntentBits } = require('discord.js');
const { Player } = require('discord-player');
const { DefaultExtractors } = require('@discord-player/extractor');
const youtubedl = require('youtube-dl-exec');
require('dotenv').config();

// Create a new Discord client
const client = new Client({
  intents: [
    GatewayIntentBits.Guilds,
    GatewayIntentBits.GuildMessages,
    GatewayIntentBits.GuildVoiceStates,
    GatewayIntentBits.MessageContent,
  ],
});

// Initialize the Player
const player = new Player(client);

// Load default extractors
(async () => {
  try {
    await player.extractors.loadMulti(DefaultExtractors);
    console.log('Loaded default extractors successfully');
  } catch (err) {
    console.error('Failed to load extractors:', err);
  }
})();

// Bot is ready
client.once('ready', () => {
  console.log(`Logged in as ${client.user.tag}`);
});

// Handle commands
client.on('messageCreate', async (message) => {
  if (!message.content.startsWith('!') || message.author.bot) return;

  const args = message.content.slice(1).trim().split(/ +/);
  const command = args.shift().toLowerCase();

  if (command === 'play') {
    if (!args[0]) {
      return message.reply('Please provide a YouTube link.');
    }
    let query = args.join(' ');

    // Remove extra YT parameters like "&list" or "&start_radio"
    try {
      const urlObj = new URL(query);
      urlObj.searchParams.delete('list');
      urlObj.searchParams.delete('start_radio');
      query = urlObj.toString();
      console.log('Cleaned link:', query);
    } catch {
      // If it's not a valid URL, fallback to user query
    }

    console.log(`Searching for: ${query}`);

    // Create or retrieve the queue
    const queue = player.nodes.create(message.guild, {
      metadata: {
        channel: message.channel,
      },
    });

    try {
      if (!queue.connection) {
        await queue.connect(message.member.voice.channel);
      }
    } catch {
      queue.delete();
      return message.reply('Could not join your voice channel!');
    }

    // Clear the queue before adding the new track
    queue.clear();

    try {
      // Fetch video info using youtube-dl-exec
      const ytInfo = await youtubedl(query, {
        dumpSingleJson: true,
        noCheckCertificates: true,
        noWarnings: true,
        preferFreeFormats: true,
        addHeader: [
          'referer:youtube.com',
          'user-agent:googlebot'
        ]
      });

      const track = {
        title: ytInfo.title || 'Unknown Title',
        url: query,
      };

      // Log the actual URL the bot will play
      console.log('Playing track URL:', track.url);

      // Add track to queue
      queue.addTrack(track);

      // Play if not already playing
      if (!queue.isPlaying()) {
        // Create a readable stream using youtube-dl-exec
        const playStream = youtubedl.exec(query, {
          format: 'bestaudio',
          noCheckCertificates: true,
          noWarnings: true,
          preferFreeFormats: true,
          addHeader: [
            'referer:youtube.com',
            'user-agent:googlebot'
          ]
        }, { stdio: ['ignore', 'pipe', 'ignore'] });

        queue.node.play(playStream.stdout, {
          type: 'opus', // Ensures proper playback
        });
        message.channel.send(`Now playing: **${track.title}**`);
      } else {
        message.channel.send(`Added to queue: **${track.title}**`);
      }
    } catch (error) {
      console.error('Error fetching video info:', error);
      message.reply('There was an error fetching the video info.');
    }
  }

  if (command === 'stop') {
    const queue = player.nodes.get(message.guild.id);
    if (!queue || !queue.isPlaying()) {
      return message.reply('No music is currently playing.');
    }
    queue.delete();
    message.channel.send('Stopped the music.');
  }

  if (command === 'skip') {
    const queue = player.nodes.get(message.guild.id);
    if (!queue || !queue.isPlaying()) {
      return message.reply('No music is currently playing.');
    }
    queue.node.skip();
    message.channel.send('Skipped the current track.');
  }
});

// Automatically skip tracks with an undefined title
player.events.on('playerStart', (queue, track) => {
  if (!track.title) {
    console.log('Automatically skipping track with undefined title');
    queue.node.skip();
  }
});

// Handle player errors
player.events.on('playerError', (queue, error) => {
  console.error(`Player error in ${queue.guild.name}:`, error);
  queue.metadata.channel.send('An error occurred while playing the track. Skipping...');
  queue.node.skip();
});

player.events.on('error', (queue, error) => {
  console.error(`Error in ${queue.guild.name}:`, error);
});

// Log in with your bot token
client.login(process.env.DISCORD_BOT_TOKEN);