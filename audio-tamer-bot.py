import os
import re
from telebot.async_telebot import AsyncTeleBot
from telebot import types
import spotipy
from spotipy.oauth2 import SpotifyOAuth
from ytmusicapi import YTMusic
import yt_dlp
from fuzzywuzzy import fuzz
import asyncio
from googleapiclient.discovery import build
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
YOUTUBE_API_KEY = os.getenv('YOUTUBE_API_KEY')
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI')

MAX_CONCURRENT_REQUESTS = 5

sp = spotipy.Spotify(auth_manager=SpotifyOAuth(client_id=SPOTIFY_CLIENT_ID,
                                               client_secret=SPOTIFY_CLIENT_SECRET,
                                               redirect_uri=SPOTIFY_REDIRECT_URI,
                                               scope="playlist-read-private"))

ytmusic = YTMusic()
youtube = build('youtube', 'v3', developerKey=YOUTUBE_API_KEY)
bot = AsyncTeleBot(TELEGRAM_TOKEN)

request_queue = asyncio.Queue()
user_states = {}

async def search_youtube(query):
    request = youtube.search().list(
        q=query,
        part='snippet',
        type='video',
        maxResults=5
    )
    response = request.execute()
    return response['items']

def set_ydl_opts(track_name, artist_name, bitrate):
    return {
        'format': 'bestaudio/best',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': bitrate,
        }],
        'outtmpl': f'audio/{track_name}',
        'noplaylist': True,
        'postprocessor_args': ['-metadata', f'artist={artist_name}', '-metadata', f'title={track_name}'],
    }

def get_bitrate_keyboard():
    keyboard = types.InlineKeyboardMarkup()
    bitrates = ['128 Kbps', '192 Kbps', '256 Kbps', '320 Kbps']

    for bitrate in bitrates:
        button = types.InlineKeyboardButton(text=bitrate, callback_data=f'bitrate_{bitrate.split(" ")[0]}')
        keyboard.add(button)

    return keyboard

async def search_youtube_and_download(track_name, artist_name, selected_bitrate):
    query = f"{artist_name} - {track_name}"
    
    search_results = await search_youtube(query)
    
    video_title = search_results[0]['snippet']['title']
    video_id = search_results[0]['id']['videoId']
    video_url = f"https://www.youtube.com/watch?v={video_id}"
    
    ydl_opts = set_ydl_opts(track_name, artist_name, selected_bitrate)
        
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([video_url])
    
async def download_song(track_name, artist_name, selected_bitrate):
    query = f"{track_name} - {artist_name} (official audio)"
    
    search_results = ytmusic.search(query, filter='songs')
    
    best_matches = []
    
    for result in search_results:
        song_title = result.get('title', '').strip().lower()
        song_artists = ", ".join([artist['name'].strip().lower() for artist in result.get('artists', [])])
        
        title_match = fuzz.ratio(track_name.lower(), song_title)
        artist_match = fuzz.ratio(artist_name.lower(), song_artists)

        avg_match = (title_match + artist_match) / 2
        
        best_matches.append((avg_match, result))

    best_matches.sort(key=lambda x: x[0], reverse=True)
    
    best_match = best_matches[0] if best_matches else None

    if best_match and best_match[0] > 70:
        result = best_match[1]
        song_title = result.get('title', '')
        video_url = f"https://www.youtube.com/watch?v={result['videoId']}"

        ydl_opts = set_ydl_opts(track_name, artist_name, selected_bitrate)
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([video_url])
    else:
        await search_youtube_and_download(track_name, artist_name, selected_bitrate)

async def send_files(chat_id, files):
    for file_path in files:
        if os.path.exists(file_path):
            with open(file_path, 'rb') as audio_file:
                await bot.send_audio(chat_id, audio_file)
            os.remove(file_path)

async def send_file(chat_id, file):
    await bot.send_audio(chat_id, open(file, 'rb'))
    os.remove(file)
        
def is_playlist_link(link):
    playlist_pattern = r"(https://open\.spotify\.com/playlist/[^?]+)"
    return re.match(playlist_pattern, link)

def is_album_link(link):
    album_pattern = r"(https://open\.spotify\.com/album/[^?]+)"
    return re.match(album_pattern, link)

def is_track_link(link):
    track_pattern = r"(https://open\.spotify\.com/track/[^?]+)"
    return re.match(track_pattern, link)
    
async def process_request(message):
    await request_queue.put(message)
    await bot.send_message(message.chat.id, "Your request is in the queue. Please wait...")
    
async def handle_requests():
    while True:
        message = await request_queue.get()
        try:
            await download_playlist(message)
        finally:
            request_queue.task_done()
        
@bot.message_handler(commands=['start'])
async def send_welcome(message):
    welcome_message = r"""
    *Hello {username}\!*
I am a bot that can help you to download your public Spotify playlist/album/track in MP3 format\.
    """.format(username=message.from_user.first_name.replace("_", r"\_").replace("*", r"\*").replace("(", r"\(").replace(")", r"\)"))
    warning_message = r"""
    ⚠️ *Important Notice* ⚠️

    This service is intended to allow users to download audio for *personal use only*\. We recognize that in certain situations, accessing legal streaming services may be difficult due to regional restrictions, connectivity issues, or personal circumstances\. However, we strongly encourage you to use the downloaded content *responsibly* and *not to infringe upon copyright laws*\. We are *not responsible* for your actions\. 

    For the best experience and to support your favorite artists, we recommend using official streaming platforms such as:

    🎵 [Spotify](https://www.spotify.com)
    🎵 [Apple Music](https://www.apple.com/music/)
    🎵 [YouTube Music](https://music.youtube.com)
    🎵 [Amazon Music](https://music.amazon.com)
    🎵 [Deezer](https://www.deezer.com)

    Remember, these platforms provide high\-quality audio and legal access to a vast catalog of music\. By choosing them, you are helping to ensure that creators are fairly compensated for their work\.

    *Thank you* for your understanding and cooperation\!
    """
    info_message = """
    So, If you read my warning and still decide to download your playlist/album/track, than send me Spotify link like that:
                       
/download playlist_link
/download album_link
/download track_link
    """
    await bot.reply_to(message, welcome_message, parse_mode='MarkdownV2')
    await bot.send_message(message.chat.id, warning_message, parse_mode='MarkdownV2', disable_web_page_preview=True)
    await bot.send_message(message.chat.id, info_message)

@bot.message_handler(commands=['download'])
async def download_playlist(message):
    try:
        link = message.text.split()[1]
        
        if is_playlist_link(link) or is_album_link(link):
            playlist_id = link.split("/")[-1].split("?")[0]
            await bot.reply_to(message, f"Getting playlist from Spotify: {playlist_id}...")
            results = sp.playlist_tracks(playlist_id)

            tracks = []
            i = 0
            for item in results['items']:
                i += 1
                track = item['track']
                track_name = track['name']
                artist_name = track['artists'][0]['name']
                tracks.append(f"{i}. {track_name} - {artist_name}")
            user_states[message.chat.id] = {'type': 'playlist', 'tracks': tracks}
            await bot.send_message(message.chat.id, "\n".join(tracks) + "\n\nChoose audio quality:", reply_markup=get_bitrate_keyboard())

        elif is_track_link(link):
            track_id = link.split("/")[-1].split("?")[0]
            await bot.reply_to(message, f"Getting track from Spotify: {track_id}...")
            track = sp.track(track_id)
            track_name = track['name']
            artist_name = track['artists'][0]['name']
            user_states[message.chat.id] = {'type': 'track', 'track_name': track_name, 'artist_name': artist_name}
            await bot.send_message(message.chat.id, f"{track_name} - {artist_name}\n\nChoose audio quality:", reply_markup=get_bitrate_keyboard())
                
        else:
            await bot.reply_to(message, "Please send a valid Spotify playlist or track link.")
        
    except IndexError:
        await bot.reply_to(message, "Please send a Spotify playlist or track link in the format: /download playlist_or_track_link")
    except Exception as e:
        await bot.reply_to(message, f"Something went wrong: {str(e)}")    

@bot.callback_query_handler(func=lambda call: call.data.startswith('bitrate_'))
async def handle_bitrate_selection(call):
    selected_bitrate = call.data.split('_')[1]
    user_type = user_states.get(call.message.chat.id, {}).get('type')
    if user_type == 'playlist':
        tracks = user_states[call.message.chat.id]['tracks']
        await bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text="\n".join(tracks) + f"\n\nYour audio quality: {selected_bitrate} Kbps.")
        response = await bot.send_message(call.message.chat.id, f"Downloading tracks...")
        audios = []
        for index, track in enumerate(tracks):
            track_info = track.split(' - ')
            track_name = track_info[0].split('. ', 1)[1]
            artist_name = track_info[1] if len(track_info) > 1 else "Unknown Artist"
            await bot.edit_message_text(chat_id=call.message.chat.id, message_id=response.message_id, text=f"\n\nDownloading {track_name} by {artist_name}...\n{index}/{len(tracks)}")
            attempts = 0
            while attempts < 5:
                try:
                    await download_song(track_name, artist_name, selected_bitrate)
                    break
                except Exception as e:
                    print(f"Error downloading song: {e}")
                    attempts += 1
            else:
                await bot.send_message(call.message.chat.id, f"Failed to download {track_name} by {artist_name}. Skipping.")
                continue
            file_path = f"audio/{track_name}.mp3"
            audios.append(file_path)
        
        await bot.edit_message_text(chat_id=call.message.chat.id, message_id=response.message_id, text=f"All {len(tracks)} tracks downloaded successfully!")
        await send_files(call.message.chat.id, audios)
        await bot.reply_to(call.message, "Download completed!")

    elif user_type == 'track':
        track_name = user_states[call.message.chat.id]['track_name']
        artist_name = user_states[call.message.chat.id]['artist_name']
        await bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.message_id, text=f"{track_name} - {artist_name}\n\nYour audio quality: {selected_bitrate} Kbps.")
        response = await bot.send_message(call.message.chat.id, f"Downloading {track_name} by {artist_name}...")
        attempts = 0
        is_downloaded = True
        while attempts < 5:
            try:
                await download_song(track_name, artist_name, selected_bitrate)
                break
            except Exception as e:
                print(f"Error downloading song: {e}")
                attempts += 1
        else:
            await bot.send_message(call.message.chat.id, f"Failed to download {track_name} by {artist_name}.")
            is_downloaded = False
                
        if is_downloaded:
            file_path = f"audio/{track_name}.mp3"
            await bot.edit_message_text(chat_id=call.message.chat.id, message_id=response.message_id, text=f"{track_name} by {artist_name} downloaded successfully!")
            await send_file(call.message.chat.id, file_path)
            await bot.reply_to(call.message, "Download completed!")

    user_states.pop(call.message.chat.id, None)

async def main():
    asyncio.create_task(handle_requests())
    await bot.polling()

if __name__ == "__main__":
    asyncio.run(main())
