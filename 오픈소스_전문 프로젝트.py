# -*- coding: euc-kr -*-

import discord
from discord.ext import commands
import speech_recognition as sr
from gtts import gTTS
import os
import openai
from googletrans import Translator
from langdetect import detect
import mysql.connector
from textrankr import TextRank
from typing import List
import asyncio
from enum import Enum
from pydub import AudioSegment
import requests
import urllib.parse
import json
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from pytz import timezone
import googlemaps

flag = 0

class MyTokenizer: # �ؽ�Ʈ�� �����Ͽ� textrank�� �����Ѵ�.
    def __call__(self, text: str) -> List[str]:
        tokens: List[str] = text.split()
        return tokens

openai.api_key = "MY_KEY" # �� �κ��� ���� APIŰ�� �޾� ���������, �� ���� ���� ����� û���Ǿ� ������ �������� ���� MY_KEY�� ��ü�Ͽ����ϴ�.

# MySQL ���� ����
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="MY_PASSWORD", # �� �κ��� MY_PASSWORD�� ��ü�մϴ�.
    database="chat_log"
)

cursor = db.cursor()
cursor.execute("""
    CREATE TABLE IF NOT EXISTS messages (
        id INT AUTO_INCREMENT PRIMARY KEY,
        role VARCHAR(10) NOT NULL,
        content TEXT NOT NULL,
        time DATETIME DEFAULT CURRENT_TIMESTAMP
    )
""") # ����, ��ȭ����, �ð� �߰�

def detect_lang(text): # �� ����, �ּ� ó���� �κ��� ��� ���� ������ ��Ȯ���� �ʾ� �ڵ��� �۵� ����� �����ϴ� �������� ó��
    #try:
    detected = detect(text)
    #except:
    #    detected = "en" # "ko"
    return detected

def save_message(role, content): # ��ȭ�� ����� ������ ����, ����, �ð��� db�� �����Ѵ�
    cursor = db.cursor()
    query = "INSERT INTO messages (role, content, time) VALUES (%s, %s, DEFAULT)"
    values = (role, content)
    cursor.execute(query, values)
    db.commit()

def get_previous_messages(): # ��ȭ������ �ð��� �������� ������������ db���� �����´�. �̶� 1���� ���� ��ȭ�� �������� �ʾ� ��ū�� �����Ѵ�. 
    # �߰��� GPT�� �亯�� 10�� �������� �����ͼ� ��ū�� �� �ٿ��ְ�, ������ �����Ѵ�.
    cursor = db.cursor()
    query = """
        SELECT content
        FROM messages
        WHERE time > NOW() - INTERVAL 1 DAY
        AND role = 'assistant'
        ORDER BY time DESC
        LIMIT 10
    """
    cursor.execute(query)
    result = cursor.fetchall() # �ش� ������ ��� �����ͼ�
    previous_messages = [row[0] for row in result]
    return previous_messages # �������ش�

def summarize_text(text: str) -> str: # textrank�� ���� ���
    # ��ȭ�� �����ؼ� ����������, ����ϸ� ����� ���� �������� ������ ���� �þ��. ���� ����� ���� 7�ٷ� �ٿ��ش�.
    mytokenizer: MyTokenizer = MyTokenizer()
    textrank: TextRank = TextRank(mytokenizer)
    
    summaries: List[str] = textrank.summarize(text, 7) # 7�� �����Ͽ� ��ȯ�� ���� ���� ������ �� �ִ�.
    summarized_text: str = '\n'.join(summaries)
    return summarized_text

intents = discord.Intents().all() # ���� �̺�Ʈ ���� �� ó���� ���� ��� ���� ���

bot = commands.Bot(command_prefix='!', intents=intents) # ��ɾ��� ���λ�� '!' ����
bot.remove_command('help') # �⺻ help ��ɾ �����ϰ� ���� ����

connections = {} # ����� ������ �����ϱ� ���� �� ��ųʸ�

@bot.event # �� �̺�Ʈ �ڵ鷯
async def on_ready(): # ���� �α��� �Ǿ��� �� ����
    print(f"���� �α��εǾ����ϴ�. �� �̸�: {bot.user.name}, �� ID: {bot.user.id}")
    bot.loop.create_task(check_alone_and_leave(bot))

@bot.event 
async def on_command_error(ctx, error): # ��ɾ ���� �� ����
    if isinstance(error, commands.CommandNotFound):
        embed = discord.Embed(title=":dotted_line_face: ��ɾ �������� �ʽ��ϴ�.",
                              description="`!help`�� �̿��� ��ɾ �ٽ� �˾ƺ�����!",
                              color=0xFF0000)
        await ctx.send(embed=embed)
    else:
        print(error)  # �ٸ� ������ �ֿܼ� ���

async def check_alone_and_leave(bot): #���� ȥ�� ����������
    while True:
        for guild in bot.guilds: # ���� ���� ��� ��������
            if guild.voice_client is not None and len(guild.voice_client.channel.members) == 1: # ���� ��� ���� üũ���� �� ���� ȥ�ڶ��
                print("���� ä�ο� ���� �����־� �����Ͽ����ϴ�.") # �ܼ� â�� ��µ˴ϴ�. ���� ȥ�� ���Ƽ� �����ߴٴ� ���� ä�ù濡 ǥ���� �ʿ���ٰ� �����Ͽ� �ܼ� â�� Ʈ��ŷ�� �������� ǥ���Ͽ����ϴ�.
                await guild.voice_client.disconnect() # ���� ä�ù濡�� ����
        await asyncio.sleep(30) # �� 30�ʸ��� ����

@bot.command() # �� ��ɾ� �ڵ鷯
async def help(ctx): # !help �Է� �� ����, ` `���� ǥ�õ� �κ��� �ڵ� ������� ���ڵ忡�� ��������
    embed = discord.Embed(title="��ɾ ����帮�ڽ��ϴ�!",
                             description="��ɾ�:\n"
                                         "`!����` - �Է��� ������� ���� ��ȭ�� ����\n"
                                         "`!����` - ���� ��ȭ�� ����\n"
                                         "`!�����ν�` - ���� �ν� ����(GPT���� ���� �Է��� �Ѱ���)\n"
                                         "`!�׸�` - ���� �ν� ����\n"
                                         "`!gpt` `�Է��� ����` - GPT���� `�Է��� ����`�� �Ѱ���\n"
                                         "`!����` `Ű����` - `Ű����`�� ���̹� ���� �˻�\n"
                                         "`!����` `������` - `������`�� ���� �˻�\n",
                             color=0x546e7a)
    await ctx.send(embed=embed) # �Ӻ��� �������� !help�� �Էµ� ä�ù濡 ����

@bot.command()
async def ����(ctx): # !���� �Է� �� ����
    voice = ctx.author.voice
    if voice is None: # ���� ���¸� Ȯ���� ����ڰ� ����ä�ο� ���ٸ�
        embed = discord.Embed(title=":x: ���� ����",
                              description="���� ä�ο� ���� �������ּ���.",
                              color=0xFF0000)
        await ctx.send(embed=embed) # �Ӻ��� �������� !���Ͱ� �Էµ� ä�ù濡 ���� ����
        return

    channel = ctx.author.voice.channel # �װ� �ƴ϶��
    voice_client = await channel.connect() # ���� ��

    embed = discord.Embed(title=":white_check_mark: ���� �Ϸ�",
                          description=f"���� ä�� `{channel.name}`�� �����߽��ϴ�.",
                          color=0x00FF00)
    await ctx.send(embed=embed) # �Ӻ��� �������� ���� �ϷḦ ä�ù濡 ����

@bot.command()
async def ����(ctx): # !���� �Է� �� ����
    voice = ctx.author.voice
    if voice is None: # ���� ä�ο� ������� �ʾҴٸ�
        embed = discord.Embed(title=":x: ���� ����",
                              description="���� ���� ä�ο� �������� �ʾҽ��ϴ�.",
                              color=0xFF0000)
        await ctx.send(embed=embed)
        return # ���� ���

    await ctx.voice_client.disconnect() # �ƴٸ� ���� ��

    embed = discord.Embed(title=":white_check_mark: ���� �Ϸ�",
                          description="���� ���� ä�ο��� �����Ͽ����ϴ�.",
                          color=0x00FF00)
    await ctx.send(embed=embed) # ���� �Ϸ� �޼��� ä�ù濡 ����


async def play_message(voice_client, message): # ���� ��� �Լ�
    tts = gTTS(text=message, lang='ko') # ������ �μ��� �޾� �ѱ����� TTS�� ����
    filename = 'tts.mp3'
    tts.save(filename)

    audio_source = discord.FFmpegPCMAudio(filename) # ���ڵ忡�� FFmpeg ����� ���

    voice_client.play(audio_source) # ��� ��

    while voice_client.is_playing(): # ����� �Ϸ�� ������ ���
        await asyncio.sleep(1)

    voice_client.stop() # ����� ����
    os.remove(filename) # ���� ����

@bot.command()
async def �����ν�(ctx): # !�����ν� �Է� �� ����
    global flag
    voice = ctx.author.voice

    if not voice:
        embed = discord.Embed(title=":warning: ����",
                              description="���� ä�ο� ���� �ʽ��ϴ�.",
                              color=0xD60000)
        return await ctx.send(embed=embed)

    vc = ctx.voice_client

    if vc is None:
        vc = await voice.channel.connect()

    connections.update({ctx.guild.id: vc})

    await play_message(vc, "���ϼ���") # ���ϼ��� ���� ���
    flag = 0
    vc.start_recording(
        discord.sinks.MP3Sink(),  # MP3 �������� ���ڵ�
        once_done,  # stop_recording �� �ݹ� �Լ� ����
        ctx.channel  # ������ ä��
    )

    await asyncio.sleep(5) # �� 5�ʰ� ���� ����
    if flag == 1: # �߰��� !�׸��� ����Ǹ� �÷��װ� 1�� �Ǿ� �Լ� Ż��(��� ������ �۾��� !�׸����� ����ȴ�)
        return
    await play_message(vc, "���� �Ϸ�") # �Ϸ� ���� ���
    vc.stop_recording()

    embed = discord.Embed(title=":ballot_box_with_check: ���� �Ϸ� :microphone2:",
                          description="������ �Ϸ�Ǿ����ϴ�.",
                          color=0x00FF90)
    await ctx.send(embed=embed) # �Ϸ� �޼��� ä�ù濡 ����

async def once_done(sink: discord.sinks, channel: discord.TextChannel, *args): 
    recorded_users = [
        f"<@{user_id}>"
        for user_id, audio in sink.audio_data.items()
    ] # ������ ����� ���� �� ���

    for user_id, audio in sink.audio_data.items():
        with open(f"output.{sink.encoding}", "wb") as f:
            f.write(audio.file.getbuffer()) # ���� ���� ���Ϸ� ������

    files = [discord.File(audio.file, f"output.{sink.encoding}") for user_id, audio in sink.audio_data.items()]  # ���ڵ� ���� ��ü�� ����Ʈ�� ����

    mp3_file = f"output.{sink.encoding}"
    wav_file = "output.wav"

    audio = AudioSegment.from_file(mp3_file, format=sink.encoding)
    audio.export(wav_file, format="wav") # ���� �����ν��� ���� mp3 ������ wav ���Ϸ� ��ȯ 
    # �߿� ��� ���� : wav ������ �ٷ� �ѱ�� ���ڵ����� ������ ����� ������ ���� ����, ���� �ν��� �۵����� �ʾ� ���� ���� ������ �� �� �� ��ȯ���־����ϴ�.

    voice_state = channel.guild.voice_client
    if voice_state is None:
        voice_client = await channel.connect()
    else:
        voice_client = voice_state

    r = sr.Recognizer()
    file_path = wav_file
    text = None

    with sr.AudioFile(file_path) as source: # ������ �����ν�
        audio_data = r.record(source)
        try:
            # ���� �ν� ����
            text = r.recognize_google(audio_data, language='ko-KR, en-US' )  # �ѱ��� or ����� �ν�
            print("���� �ν� ���:", text) # �ܼ�â�� �ν� ��� ���
        except sr.UnknownValueError:
            print("������ �ν��� �� �������ϴ�.")
        except sr.RequestError as e:
            print("���� �ν� ���񽺿� ������ �߻��߽��ϴ�:", str(e))

    if text is None: # ���� �ν��� �ȵǾ� �ƹ��͵� ���� ��쿡
        await play_message(voice_client, "������ �ν��� �� �������ϴ�") # �ȳ����� ��� ��
        os.remove(file_path) # ���� ����
        await sink.vc.disconnect() # ä�ο��� ����
        embed = discord.Embed(title=":exclamation: ���� �ν� ���� :exclamation:",
                              description="������ �Ϸ�Ǿ�����, ������ �νĵ��� �ʾҽ��ϴ�.",
                              color=0xFFFF00)
        await channel.send(embed=embed) # ä�ù濡 ���� ���� ���
        return

    try:
        # ������� �Է� ����
        save_message("user", text)

        # ���� ������ �޾ƿ���, ���
        previous_messages = get_previous_messages()
        previous_messages_text = '\n'.join(previous_messages)
        previous_messages_summary = summarize_text(previous_messages_text)

        # ��� ������ ä�ù濡 ����, ���� ��� ������ Ȯ���� �ʿ䰡 ���� ������ ������ ����
        #summary_list = previous_messages_summary.split("\n")
        #summary_text = "".join(summary_list)
        #await channel.send(f"���: {summary_text}")

        # GPT �⺻ ���û���, ��ū �� ������ ���� ��� 2�� ���� ����, AI ���̹Ƿ� �����ϰ� ���ϵ��� ����
        initial_message=[{"role": "system", "content": "You are a helpful assistant, and answer everything at most 2 lines. Be sure to be polite."}]
        messages = [{"role": "user", "content": text}] # �Է��� ����
        messages_with_summary = initial_message + [{"role": "system", "content": previous_messages_summary}] + messages # ���� �Է¿� ���� ����

        # GPT ���� �޾ƿ�
        response = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=messages_with_summary) # gpt-3.5-turbo ���� ���
        assistant_response = response.choices[0].message['content'] # ����

        # �����ͺ��̽��� ���� ����
        save_message('assistant', assistant_response)
        token_count = response['usage']['total_tokens'] # ��ū �� �޾ƿ�

        print('�亯(GPT) : ' + assistant_response) # �ܼ�â�� �亯 ���
        print('���� ��ū ��:', token_count) # �ܼ�â�� ��ū �� ���

        detected = detect_lang(assistant_response) # ���� ��� �ν�

        if detected == "ko": # �ѱ���� �׳� ����ص� �̻��� ��۸��� ������ ������ ����
            await play_message(voice_client, assistant_response)
        else: # �׷��� �ѱ�� �ƴ϶�� ������ �Ͽ� �ѱ���� ����� ����������
            translator = Translator()
            translation = translator.translate(assistant_response, src="en", dest="ko")
            print('������ �亯(GPT): ' + translation.text) # �ܼ�â ���� �亯 ���
            embed = discord.Embed(title=":scroll: ���� �亯",
                                  description=assistant_response,
                                  color=0x00FFFF)
            await channel.send(embed=embed) # ���� �亯�� �ؽ�Ʈ ä������ ����
            await play_message(voice_client, translation.text) # �ѱ� ������ �������� ���

        # ���� ����
        os.remove(file_path)

        await sink.vc.disconnect()

        await channel.send(f":microphone: ���� ä�ο��� �νĵ� ������ �������Ϸ� �����ص帳�ϴ�! {', '.join(recorded_users)}.", files=files) # ä�ù濡 ���� ���� ���� ����
    
    except Exception as e: # ���� �߻� �� �ڵ鸵
        play_message(voice_client, "���� �ν� ���񽺿� ������ �߻��Ͽ����ϴ�")
        os.remove(file_path)
        await sink.vc.disconnect()
        embed = discord.Embed(title=":tools: ���� ���� :tools:",
                              description="������ �Ϸ�Ǿ�����, ���� ���� �ν� ���񽺿� ������ �߻��Ͽ����ϴ�. ����� �ٽ� �õ����ּ���.",
                              color=0x9B0000)
        await channel.send(embed=embed)

    #db.close()

@bot.command()
async def gpt(ctx, *, text=None): # !gpt `�޽���` �Է� �� ����, ��κ��� �۵��� !�����νİ� ����մϴ�
    
    if text is None:
        embed = discord.Embed(title=":green_book: �Էµ� �ؽ�Ʈ�� �����ϴ�. :x:",
                              description="AI ê���� �Է��� �־�� ������ �� �� �־��.",
                              color=0x9B0000)
        await ctx.send(embed=embed)
        return
    # ������� �Է� ����
    save_message("user", text)

    # ���� ������ �޾ƿ���, ���
    previous_messages = get_previous_messages()
    previous_messages_text = '\n'.join(previous_messages)
    previous_messages_summary = summarize_text(previous_messages_text)

    #summary_list = previous_messages_summary.split("\n")
    #summary_text = "".join(summary_list)
    #await ctx.send(f"���: {summary_text}")

    initial_message=[{"role": "system", "content": "You are a helpful assistant, and answer everything at most 3 lines. Be sure to be polite."}]
    messages = [{"role": "user", "content": text}]
    messages_with_summary = initial_message + [{"role": "system", "content": previous_messages_summary}] + messages

    # GPT ���� �޾ƿ�
    response = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=messages_with_summary)
    assistant_response = response.choices[0].message['content']

    # �����ͺ��̽��� ���� ����
    save_message('assistant', assistant_response)
    token_count = response['usage']['total_tokens']

    print('�亯(GPT) : ' + assistant_response)
    print('���� ��ū ��:', token_count) # ��ū �� ���

    detected = detect_lang(assistant_response)

    if detected == "ko":
        embed1 = discord.Embed(title=":loud_sound: �亯",
                               description=assistant_response,
                               color=0x00FFFF)
        await ctx.send(embed=embed1) # ä������ �亯 ����
    else: # ä������ ����, ������ �亯 ����
        translator = Translator()
        translation = translator.translate(assistant_response, src="en", dest="ko")
        print('������ �亯(GPT): ' + translation.text)
        embed1 = discord.Embed(title=":scroll: ���� �亯",
                              description=assistant_response,
                              color=0x00FFFF)
        await ctx.send(embed=embed1)
        embed2 = discord.Embed(title=":bookmark: ������",
                              description=translation.text,
                              color=0x430ea2)
        await ctx.send(embed=embed2)

@bot.command()
async def �׸�(ctx):
    global flag
    if ctx.guild.id in connections:  # ĳ�ÿ� ���� ���(����)�� ������ �Ǿ����� Ȯ��. ���� ������ �Ǿ��ٸ� �Ʒ� ����
        vc = connections[ctx.guild.id] 
        await play_message(vc, "���� ����") # ���� ��Ʈ ���� ��
        flag = 1 # �÷��� 1�� ����. �� ��� ������ ������ �Ϸ��Ѱ� �ƴ϶� ���� ���������Ƿ� ����Ѵ�.
        vc.stop_recording()  # ���� ����, �Ŀ� once_done �ݹ� �Լ� ȣ��.
        del connections[ctx.guild.id]  # ĳ�ÿ��� �ش� ���(����) ����.
        await ctx.delete()  # ����.
    else:
        embed = discord.Embed(title=":mute: ���� ����",
                              description="���� ���� �ƴϿ���.",
                              color=0x9B0000)
        await ctx.send(embed=embed)  # ���� ���� �ƴ� ��� �Ӻ��� �������� ���

@bot.command()
async def ����(ctx, *, keywords=None): # !���� �Է� �� ����
    naver_client_id = "MY_CLIENT_ID" # ���� ������ ��ü�մϴ�
    naver_client_secret = "MY_CLIENT_SECRET" # ���� ������ ��ü�մϴ�

    if keywords is None: # Ű���� ���Է� �� �ڵ鸵
        embed = discord.Embed(title=":warning: Ű���带 �Է����ּ���. :pencil:",
                              description="������ �̸� �����մϴ�. ������ ã�� �� �־ `!����`�� �Է��ϽŰ� �ƴѰ���?",
                              color=0x9B0000)
        await ctx.send(embed=embed)
        return

    search_query = keywords # �˻� �ܾ�
    url = 'https://openapi.naver.com/v1/search/news.json' # ��������
    headers = {
        'X-Naver-Client-Id': naver_client_id,
        'X-Naver-Client-Secret': naver_client_secret
    }
    parameters = {
        'query': search_query,  # �˻��� ����
        'display': 3,  # ������ ���� ���� ����
        'sort': 'sim' # ���ü� ���� ���� ����
    }

    try:
        response = requests.get(url, headers=headers, params=parameters) # URL�� Get ��û�� ������ �޾ƿ�
        data = response.json() # JSON ���� �Ľ�
        articles = data['items'] # ���� ��縦 ������

        for article in articles: # ���� ����, ��ũ�� �������µ�, �̶� beautifulsoup�� ����� �ؽ�Ʈ�� �̻��� �ܾ ���� �ʵ��� �Ѵ�
            title_html = article['title']
            title_text = BeautifulSoup(title_html, 'html.parser').get_text()
            link = article['link']
            news_info = f"**{title_text}**\n��ũ: {link}"
            await ctx.send(news_info)

        more_link = f"�� ����: https://search.naver.com/search.naver?where=news&ie=utf8&sm=nws_hty&query={urllib.parse.quote(search_query)}" # �� ����� ���� �˻�� ���� ��ũ��
        await ctx.send(more_link) # ä�ù濡 �������ش�

    except Exception as e: # ���� �޾ƿ��µ� �������� �ڵ鸵
        embed = discord.Embed(title=":tools: �о���� ���� �߻� :tools:",
                              description="���� ������ �������µ� �����Ͽ����ϴ�. ��� �� �ٽ� �õ����ּ���.",
                              color=0x9B0000)
        await ctx.send(embed=embed)

def get_weather(nx, ny): # ���� ���� �޾ƿ���
    base_url = 'http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst' # ���û ���� ����
    service_key = 'MY_SERVICE_KEY'  # ���û ���� ���� API ���� ���ڵ� �� Ű. �̰��� ����ؾ� ������ �ȳ�. ���� ������ ��ü
    #service_key = 'DECODED_KEY'  # ���û ���� ���� API ���� Ű ���ڵ�. �̰��� ����ϸ� ������ ��. ���� ������ ��ü
    service_key_decoded = urllib.parse.unquote_plus(service_key, encoding='UTF-8') # ���ڵ� �� Ű�� ���ڵ��ؼ� ����ؾ���.

    now = datetime.now(timezone('Asia/Seoul')) # ���� �ð�(���� ǥ�ؽ�)�� ������
    hour = int(now.strftime("%H")) # �� ������ ������ �޾ƿͼ�

    # ���û ������Ʈ �ð��� ���� base_time ����
    # ���û ���� ������Ʈ�� 3�ð����� �̷������, Ȥ�ö� �������� ��츦 ����� 6�ð� ������ ������ �����ɴϴ�.
    if hour < 2:
        base_time = "2000"
        base_date = (now - timedelta(days=1)).strftime("%Y%m%d")
    elif hour < 5:
        base_time = "2300"
        base_date = (now - timedelta(days=1)).strftime("%Y%m%d")
    elif hour < 8:
        base_time = "0200"
        base_date = now.strftime("%Y%m%d")
    elif hour < 11:
        base_time = "0800"
        base_date = now.strftime("%Y%m%d")
    elif hour < 14:
        base_time = "1100"
        base_date = now.strftime("%Y%m%d")
    elif hour < 17:
        base_time = "1400"
        base_date = now.strftime("%Y%m%d")
    elif hour < 20:
        base_time = "1700"
        base_date = now.strftime("%Y%m%d")
    else:
        base_time = "2000"
        base_date = now.strftime("%Y%m%d")
    # �ܱ� ���� 1�ð� �з��� ���� 14������ �Ǿ ��뷮�� ���̱� ���� 14�ٸ� ���������� ����
    parameters = { 
        'serviceKey': service_key_decoded,
        'pageNo': 1,
        'numOfRows': 14,
        'dataType': 'JSON',
        'base_date': base_date,
        'base_time': base_time,
        'nx': int(nx),
        'ny': int(ny)
    }

    url = base_url + '?' + urllib.parse.urlencode(parameters)
    print(url)

    forecast_response = requests.get(base_url, params=parameters)
    forecast_data = forecast_response.json() # ������ �����ͼ�
    print(forecast_data) # �ܼ�â�� ����� �����
    if forecast_data['response']['header']['resultCode'] == '00':
        # ������ ��ȯ
        return forecast_data['response']['body']['items']['item']
    else:
        return None
    
@bot.command()
async def ����(ctx, *, location=None):
    #thumbnail_url = None # ���� ���� �ʱ�ȭ
    googlemaps_api_key = 'MY_MAPS_KEY'  # Google Maps API Ű, ���� ������ ��ü�մϴ�.
    gmaps = googlemaps.Client(key=googlemaps_api_key)

    if location is None:
        embed = discord.Embed(title=":warning: ������ �Է����ּ���. :mag_right:",
                              description="�ּ��� `������`������ �Է����ֽ� �� �������ݾƿ�~",
                              color=0x9B0000)
        await ctx.send(embed=embed) # �������� ������ ���� ���
        return
    
    geocode_result = gmaps.geocode(location) # �����ڵ��� ���� ������ ���� ���� �浵 ��ǥ�� �˾ƿ´�

    if geocode_result:
        location_data = geocode_result[0]['geometry']['location']
        lat = location_data['lat']  # ����
        lng = location_data['lng']  # �浵

        nx = lat
        ny = lng

        weather_data = get_weather(nx, ny) # ���� ������ �޾ƿ� ��
        if weather_data:
            weather_info = ""
            for item in weather_data:
                base_time = item['baseTime']
                if base_time == "2300":
                    fcst_time = "0000"
                else:
                    fcst_time = str(int(base_time) + 100).zfill(4)  # .zfill(4)�� ����Ͽ� �׻� 4�ڸ� ���ڿ��� �ǵ��� �Ѵ�. �� ������ 2�ڸ� ���ڰ� �ƴҶ��� ���� �߻���
                #print(f"fcst_time: {fcst_time}, item['fcstTime']: {item['fcstTime']}")  # ����� ����
                if fcst_time == item['fcstTime']:
                    category = item['category']
                    value = item['fcstValue']
                    # �˸��� ���� ���� ���� ���
                    if category == 'TMP':
                        weather_info += f":thermometer: ���: {value}��C\n"
                    elif category == 'SKY':
                        if value == '1':
                            weather_info += f":white_sun_cloud: �ϴ� ����: ����\n"
                            thumbnail_url = 'https://ifh.cc/g/NXo1D4.png'
                        elif value == '3': # �ڷῡ value�� 2�� ��찡 ������ �ʾ� ���� �ʾҽ��ϴ�.
                            weather_info += f":white_sun_cloud: �ϴ� ����: ���� ����\n"
                            thumbnail_url = 'https://ifh.cc/g/KmH9CA.png'
                        elif value == '4':
                            weather_info += f":white_sun_cloud: �ϴ� ����: �帲\n"
                            thumbnail_url = 'https://ifh.cc/g/fl08Sg.png'
                    elif category == 'PTY':
                        if value == '0':
                            weather_info += f":umbrella2: ���� ����: ����\n"
                        elif value == '1':
                            weather_info += f":umbrella2: ���� ����: ��\n"
                            thumbnail_url = 'https://ifh.cc/g/1kF9f1.png'
                        elif value == '2':
                            weather_info += f":umbrella2: ���� ����: ��/��\n"
                            thumbnail_url = 'https://ifh.cc/g/JFkSfT.png'
                        elif value == '3':
                            weather_info += f":umbrella2: ���� ����: ��\n"
                            thumbnail_url = 'https://ifh.cc/g/MjPNbt.png'
                        elif value == '4':
                            weather_info += f":umbrella2: ���� ����: �ҳ���\n"
                            thumbnail_url = 'https://ifh.cc/g/poJRl5.png'
                    elif category == 'POP':
                        weather_info += f":droplet: ���� Ȯ��: {value}%\n"
                    elif category == 'PCP':
                        if value == '��������':
                            weather_info += f":sunny: 1�ð� ������: ���� ����\n"
                        else:
                            weather_info += f":cloud_rain: 1�ð� ������: {value}mm\n"
                    elif category == 'REH':
                        weather_info += f":sweat_drops: ����: {value}%\n"
                    elif category == 'TMN':
                        weather_info += f"�� ���� ���: {value}��C\n"
                    elif category == 'TMX':
                        weather_info += f"�� �ְ� ���: {value}��C\n"

            embed = discord.Embed(title=f"{location}", description=weather_info, color=0x00FFFF)
            embed.set_footer(text="���� ����")
            embed.set_thumbnail(url=thumbnail_url)

            await ctx.send(embed=embed)
        else:
            embed1 = discord.Embed(title=":grey_question: �������� �ҷ����� ���� :grey_question:",
                                   description="���� ���� ������ �������µ� �����Ͽ����ϴ�. ��� �� �ٽ� �õ����ּ���.",
                                   color=0x9B0000)
            await ctx.send(embed=embed1)
    else:
        embed2 = discord.Embed(title=":grey_question: ��ǥ���� �ҷ����� ���� :grey_question:",
                               description="��ǥ ������ �������µ� �����Ͽ����ϴ�. ��� �� �ٽ� �õ����ּ���.",
                               color=0x9B0000)
        await ctx.send(embed=embed2) # �����鿡 ���� �ڵ鸵



@bot.event
async def on_voice_state_update(member, before, after): # �ܼ�â�� �˾ƺ� �� �ֵ��� ���� ���

    print(f"Voice state update detected for member: {member.name}, Before: {before}, After: {after}")

    # ����� ���� �ƴϰų� �ڱ� �ڽ��� �ƴϸ�
    if not member.bot or member != bot.user:
        return

    # ���� ä�ο� ���� ���
    if before.channel is None and after.channel is not None:
        print(f"���� ���� ä�� {after.channel.name}�� �����Ͽ����ϴ�.")

    # ���� ä���� ������ ���
    if before.channel is not None and after.channel is None:
        print(f"���� ���� ä�� {before.channel.name}���� �����Ͽ����ϴ�.")

    # ���� ä���� �����ϴ� ���
    if before.channel is not None and after.channel is not None:
        print(f"���� ���� ä�� {before.channel.name}���� {after.channel.name}�� �̵��Ͽ����ϴ�.")

bot.run("MY_TOKEN") # ���ڵ� �� ��ū. ���Ȼ� ��ü�Ͽ����ϴ�.