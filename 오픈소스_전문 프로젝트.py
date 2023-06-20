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

class MyTokenizer: # 텍스트를 분할하여 textrank를 수행한다.
    def __call__(self, text: str) -> List[str]:
        tokens: List[str] = text.split()
        return tokens

openai.api_key = "MY_KEY" # 이 부분은 실제 API키를 받아 사용했으나, 매 사용시 마다 요금이 청구되어 유출의 위험으로 인해 MY_KEY로 대체하였습니다.

# MySQL 연결 설정
db = mysql.connector.connect(
    host="localhost",
    user="root",
    password="MY_PASSWORD", # 이 부분은 MY_PASSWORD로 대체합니다.
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
""") # 역할, 대화내용, 시간 추가

def detect_lang(text): # 언어를 감지, 주석 처리한 부분은 영어에 대한 감지가 정확하지 않아 코드의 작동 방식을 수정하는 과정에서 처리
    #try:
    detected = detect(text)
    #except:
    #    detected = "en" # "ko"
    return detected

def save_message(role, content): # 대화가 진행될 때마다 역할, 내용, 시간을 db에 저장한다
    cursor = db.cursor()
    query = "INSERT INTO messages (role, content, time) VALUES (%s, %s, DEFAULT)"
    values = (role, content)
    cursor.execute(query, values)
    db.commit()

def get_previous_messages(): # 대화내용을 시간을 기준으로 내림차순으로 db에서 가져온다. 이때 1일이 넘은 대화는 가져오지 않아 토큰을 절약한다. 
    # 추가로 GPT의 답변만 10줄 제한으로 가져와서 토큰을 더 줄여주고, 문맥을 유지한다.
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
    result = cursor.fetchall() # 해당 내용을 모두 가져와서
    previous_messages = [row[0] for row in result]
    return previous_messages # 리턴해준다

def summarize_text(text: str) -> str: # textrank를 통한 요약
    # 대화를 제한해서 가져오지만, 사용하면 사용할 수록 가져오는 문장의 수는 늘어난다. 따라서 요약을 통해 7줄로 줄여준다.
    mytokenizer: MyTokenizer = MyTokenizer()
    textrank: TextRank = TextRank(mytokenizer)
    
    summaries: List[str] = textrank.summarize(text, 7) # 7을 조절하여 반환할 문장 수를 조절할 수 있다.
    summarized_text: str = '\n'.join(summaries)
    return summarized_text

intents = discord.Intents().all() # 봇의 이벤트 수신 및 처리에 관한 모든 권한 허용

bot = commands.Bot(command_prefix='!', intents=intents) # 명령어의 접두사는 '!' 형식
bot.remove_command('help') # 기본 help 명령어를 제거하고 직접 구현

connections = {} # 연결된 서버를 추적하기 위한 빈 딕셔너리

@bot.event # 봇 이벤트 핸들러
async def on_ready(): # 봇이 로그인 되었을 때 수행
    print(f"봇이 로그인되었습니다. 봇 이름: {bot.user.name}, 봇 ID: {bot.user.id}")
    bot.loop.create_task(check_alone_and_leave(bot))

@bot.event 
async def on_command_error(ctx, error): # 명령어가 없을 때 수행
    if isinstance(error, commands.CommandNotFound):
        embed = discord.Embed(title=":dotted_line_face: 명령어가 존재하지 않습니다.",
                              description="`!help`를 이용해 명령어를 다시 알아보세요!",
                              color=0xFF0000)
        await ctx.send(embed=embed)
    else:
        print(error)  # 다른 에러는 콘솔에 출력

async def check_alone_and_leave(bot): #봇이 혼자 남아있을때
    while True:
        for guild in bot.guilds: # 봇이 속한 모든 서버에서
            if guild.voice_client is not None and len(guild.voice_client.channel.members) == 1: # 봇이 멤버 수를 체크했을 때 본인 혼자라면
                print("음성 채널에 봇만 남아있어 퇴장하였습니다.") # 콘솔 창에 출력됩니다. 굳이 혼자 남아서 퇴장했다는 말은 채팅방에 표시할 필요없다고 생각하여 콘솔 창에 트래킹을 목적으로 표시하였습니다.
                await guild.voice_client.disconnect() # 음성 채팅방에서 퇴장
        await asyncio.sleep(30) # 매 30초마다 수행

@bot.command() # 봇 명령어 핸들러
async def help(ctx): # !help 입력 시 실행, ` `으로 표시된 부분은 코드 블록으로 디스코드에서 보여진다
    embed = discord.Embed(title="명령어를 설명드리겠습니다!",
                             description="명령어:\n"
                                         "`!들어와` - 입력한 사용자의 음성 대화방 입장\n"
                                         "`!나가` - 음성 대화방 퇴장\n"
                                         "`!음성인식` - 음성 인식 시작(GPT에게 음성 입력을 넘겨줌)\n"
                                         "`!그만` - 음성 인식 중지\n"
                                         "`!gpt` `입력할 내용` - GPT에게 `입력할 내용`을 넘겨줌\n"
                                         "`!뉴스` `키워드` - `키워드`로 네이버 뉴스 검색\n"
                                         "`!날씨` `지역명` - `지역명`의 날씨 검색\n",
                             color=0x546e7a)
    await ctx.send(embed=embed) # 임베드 형식으로 !help가 입력된 채팅방에 전달

@bot.command()
async def 들어와(ctx): # !들어와 입력 시 실행
    voice = ctx.author.voice
    if voice is None: # 음성 상태를 확인해 사용자가 음성채널에 없다면
        embed = discord.Embed(title=":x: 입장 실패",
                              description="음성 채널에 먼저 입장해주세요.",
                              color=0xFF0000)
        await ctx.send(embed=embed) # 임베드 형식으로 !들어와가 입력된 채팅방에 오류 전달
        return

    channel = ctx.author.voice.channel # 그게 아니라면
    voice_client = await channel.connect() # 연결 후

    embed = discord.Embed(title=":white_check_mark: 입장 완료",
                          description=f"음성 채널 `{channel.name}`에 입장했습니다.",
                          color=0x00FF00)
    await ctx.send(embed=embed) # 임베드 형식으로 입장 완료를 채팅방에 전달

@bot.command()
async def 나가(ctx): # !나가 입력 시 실행
    voice = ctx.author.voice
    if voice is None: # 음성 채널에 연결되지 않았다면
        embed = discord.Embed(title=":x: 퇴장 실패",
                              description="봇이 음성 채널에 입장하지 않았습니다.",
                              color=0xFF0000)
        await ctx.send(embed=embed)
        return # 오류 출력

    await ctx.voice_client.disconnect() # 됐다면 퇴장 후

    embed = discord.Embed(title=":white_check_mark: 퇴장 완료",
                          description="봇이 음성 채널에서 퇴장하였습니다.",
                          color=0x00FF00)
    await ctx.send(embed=embed) # 퇴장 완료 메세지 채팅방에 전달


async def play_message(voice_client, message): # 음성 재생 함수
    tts = gTTS(text=message, lang='ko') # 내용을 인수로 받아 한글음성 TTS를 수행
    filename = 'tts.mp3'
    tts.save(filename)

    audio_source = discord.FFmpegPCMAudio(filename) # 디스코드에서 FFmpeg 사용해 재생

    voice_client.play(audio_source) # 재생 후

    while voice_client.is_playing(): # 재생이 완료될 때까지 대기
        await asyncio.sleep(1)

    voice_client.stop() # 오디오 중지
    os.remove(filename) # 파일 삭제

@bot.command()
async def 음성인식(ctx): # !음성인식 입력 시 실행
    global flag
    voice = ctx.author.voice

    if not voice:
        embed = discord.Embed(title=":warning: 오류",
                              description="음성 채널에 있지 않습니다.",
                              color=0xD60000)
        return await ctx.send(embed=embed)

    vc = ctx.voice_client

    if vc is None:
        vc = await voice.channel.connect()

    connections.update({ctx.guild.id: vc})

    await play_message(vc, "말하세요") # 말하세요 음성 출력
    flag = 0
    vc.start_recording(
        discord.sinks.MP3Sink(),  # MP3 형식으로 인코딩
        once_done,  # stop_recording 후 콜백 함수 지정
        ctx.channel  # 퇴장할 채널
    )

    await asyncio.sleep(5) # 약 5초간 녹음 받음
    if flag == 1: # 중간에 !그만이 수행되면 플래그가 1이 되어 함수 탈출(대신 나머지 작업은 !그만에서 수행된다)
        return
    await play_message(vc, "녹음 완료") # 완료 음성 출력
    vc.stop_recording()

    embed = discord.Embed(title=":ballot_box_with_check: 녹음 완료 :microphone2:",
                          description="녹음이 완료되었습니다.",
                          color=0x00FF90)
    await ctx.send(embed=embed) # 완료 메세지 채팅방에 전달

async def once_done(sink: discord.sinks, channel: discord.TextChannel, *args): 
    recorded_users = [
        f"<@{user_id}>"
        for user_id, audio in sink.audio_data.items()
    ] # 녹음된 사용자 저장 후 언급

    for user_id, audio in sink.audio_data.items():
        with open(f"output.{sink.encoding}", "wb") as f:
            f.write(audio.file.getbuffer()) # 녹음 내용 파일로 저장함

    files = [discord.File(audio.file, f"output.{sink.encoding}") for user_id, audio in sink.audio_data.items()]  # 디스코드 파일 객체로 리스트에 담음

    mp3_file = f"output.{sink.encoding}"
    wav_file = "output.wav"

    audio = AudioSegment.from_file(mp3_file, format=sink.encoding)
    audio.export(wav_file, format="wav") # 파일 음성인식을 위해 mp3 파일을 wav 파일로 변환 
    # 중요 고려 사항 : wav 파일을 바로 넘기면 디코딩에서 문제가 생기는 것인지 버그 인지, 음성 인식이 작동하지 않아 굳이 파일 형식을 한 번 더 변환해주었습니다.

    voice_state = channel.guild.voice_client
    if voice_state is None:
        voice_client = await channel.connect()
    else:
        voice_client = voice_state

    r = sr.Recognizer()
    file_path = wav_file
    text = None

    with sr.AudioFile(file_path) as source: # 파일을 음성인식
        audio_data = r.record(source)
        try:
            # 음성 인식 실행
            text = r.recognize_google(audio_data, language='ko-KR, en-US' )  # 한국어 or 영어로 인식
            print("음성 인식 결과:", text) # 콘솔창에 인식 결과 출력
        except sr.UnknownValueError:
            print("음성을 인식할 수 없었습니다.")
        except sr.RequestError as e:
            print("음성 인식 서비스에 오류가 발생했습니다:", str(e))

    if text is None: # 음성 인식이 안되어 아무것도 없을 경우에
        await play_message(voice_client, "음성을 인식할 수 없었습니다") # 안내음성 출력 후
        os.remove(file_path) # 파일 삭제
        await sink.vc.disconnect() # 채널에서 나감
        embed = discord.Embed(title=":exclamation: 음성 인식 실패 :exclamation:",
                              description="녹음이 완료되었으나, 음성이 인식되지 않았습니다.",
                              color=0xFFFF00)
        await channel.send(embed=embed) # 채팅방에 오류 문구 출력
        return

    try:
        # 사용자의 입력 저장
        save_message("user", text)

        # 이전 응답을 받아오고, 요약
        previous_messages = get_previous_messages()
        previous_messages_text = '\n'.join(previous_messages)
        previous_messages_summary = summarize_text(previous_messages_text)

        # 요약 내용을 채팅방에 보냄, 굳이 요약 내용을 확인할 필요가 없을 것으로 생각해 삭제
        #summary_list = previous_messages_summary.split("\n")
        #summary_text = "".join(summary_list)
        #await channel.send(f"요약: {summary_text}")

        # GPT 기본 지시사항, 토큰 수 절약을 위해 대답 2줄 제한 설정, AI 비서이므로 공손하게 답하도록 설정
        initial_message=[{"role": "system", "content": "You are a helpful assistant, and answer everything at most 2 lines. Be sure to be polite."}]
        messages = [{"role": "user", "content": text}] # 입력할 내용
        messages_with_summary = initial_message + [{"role": "system", "content": previous_messages_summary}] + messages # 실제 입력에 들어가는 내용

        # GPT 응답 받아옴
        response = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=messages_with_summary) # gpt-3.5-turbo 엔진 사용
        assistant_response = response.choices[0].message['content'] # 응답

        # 데이터베이스에 응답 저장
        save_message('assistant', assistant_response)
        token_count = response['usage']['total_tokens'] # 토큰 수 받아옴

        print('답변(GPT) : ' + assistant_response) # 콘솔창에 답변 출력
        print('사용된 토큰 수:', token_count) # 콘솔창에 토큰 수 출력

        detected = detect_lang(assistant_response) # 음성 언어 인식

        if detected == "ko": # 한국어면 그냥 재생해도 이상한 콩글리시 발음이 나오지 않음
            await play_message(voice_client, assistant_response)
        else: # 그러나 한국어가 아니라면 번역을 하여 한국어로 만들어 재생해줘야함
            translator = Translator()
            translation = translator.translate(assistant_response, src="en", dest="ko")
            print('번역된 답변(GPT): ' + translation.text) # 콘솔창 번역 답변 출력
            embed = discord.Embed(title=":scroll: 원문 답변",
                                  description=assistant_response,
                                  color=0x00FFFF)
            await channel.send(embed=embed) # 원문 답변은 텍스트 채팅으로 전달
            await play_message(voice_client, translation.text) # 한글 음성은 음성으로 재생

        # 파일 정리
        os.remove(file_path)

        await sink.vc.disconnect()

        await channel.send(f":microphone: 음성 채널에서 인식된 내용을 음성파일로 제공해드립니다! {', '.join(recorded_users)}.", files=files) # 채팅방에 내가 말한 내용 전송
    
    except Exception as e: # 오류 발생 시 핸들링
        play_message(voice_client, "음성 인식 서비스에 오류가 발생하였습니다")
        os.remove(file_path)
        await sink.vc.disconnect()
        embed = discord.Embed(title=":tools: 서비스 오류 :tools:",
                              description="녹음이 완료되었으나, 현재 음성 인식 서비스에 오류가 발생하였습니다. 잠시후 다시 시도해주세요.",
                              color=0x9B0000)
        await channel.send(embed=embed)

    #db.close()

@bot.command()
async def gpt(ctx, *, text=None): # !gpt `메시지` 입력 시 실행, 대부분의 작동은 !음성인식과 비슷합니다
    
    if text is None:
        embed = discord.Embed(title=":green_book: 입력된 텍스트가 없습니다. :x:",
                              description="AI 챗봇도 입력이 있어야 답장을 할 수 있어요.",
                              color=0x9B0000)
        await ctx.send(embed=embed)
        return
    # 사용자의 입력 저장
    save_message("user", text)

    # 이전 응답을 받아오고, 요약
    previous_messages = get_previous_messages()
    previous_messages_text = '\n'.join(previous_messages)
    previous_messages_summary = summarize_text(previous_messages_text)

    #summary_list = previous_messages_summary.split("\n")
    #summary_text = "".join(summary_list)
    #await ctx.send(f"요약: {summary_text}")

    initial_message=[{"role": "system", "content": "You are a helpful assistant, and answer everything at most 3 lines. Be sure to be polite."}]
    messages = [{"role": "user", "content": text}]
    messages_with_summary = initial_message + [{"role": "system", "content": previous_messages_summary}] + messages

    # GPT 응답 받아옴
    response = openai.ChatCompletion.create(model="gpt-3.5-turbo", messages=messages_with_summary)
    assistant_response = response.choices[0].message['content']

    # 데이터베이스에 응답 저장
    save_message('assistant', assistant_response)
    token_count = response['usage']['total_tokens']

    print('답변(GPT) : ' + assistant_response)
    print('사용된 토큰 수:', token_count) # 토큰 수 출력

    detected = detect_lang(assistant_response)

    if detected == "ko":
        embed1 = discord.Embed(title=":loud_sound: 답변",
                               description=assistant_response,
                               color=0x00FFFF)
        await ctx.send(embed=embed1) # 채팅으로 답변 전송
    else: # 채팅으로 원문, 번역된 답변 전송
        translator = Translator()
        translation = translator.translate(assistant_response, src="en", dest="ko")
        print('번역된 답변(GPT): ' + translation.text)
        embed1 = discord.Embed(title=":scroll: 원문 답변",
                              description=assistant_response,
                              color=0x00FFFF)
        await ctx.send(embed=embed1)
        embed2 = discord.Embed(title=":bookmark: 번역됨",
                              description=translation.text,
                              color=0x430ea2)
        await ctx.send(embed=embed2)

@bot.command()
async def 그만(ctx):
    global flag
    if ctx.guild.id in connections:  # 캐시에 현재 길드(서버)에 연결이 되었는지 확인. 만약 연결이 되었다면 아래 실행
        vc = connections[ctx.guild.id] 
        await play_message(vc, "녹음 중지") # 중지 멘트 실행 후
        flag = 1 # 플래그 1로 세팅. 이 경우 녹음을 끝까지 완료한게 아니라 직접 중지했으므로 사용한다.
        vc.stop_recording()  # 녹음 중지, 후에 once_done 콜백 함수 호출.
        del connections[ctx.guild.id]  # 캐시에서 해당 길드(서버) 삭제.
        await ctx.delete()  # 삭제.
    else:
        embed = discord.Embed(title=":mute: 녹음 실패",
                              description="녹음 중이 아니에요.",
                              color=0x9B0000)
        await ctx.send(embed=embed)  # 녹음 중이 아닐 경우 임베드 형식으로 출력

@bot.command()
async def 뉴스(ctx, *, keywords=None): # !뉴스 입력 시 실행
    naver_client_id = "MY_CLIENT_ID" # 보안 문제로 대체합니다
    naver_client_secret = "MY_CLIENT_SECRET" # 보안 문제로 대체합니다

    if keywords is None: # 키워드 미입력 시 핸들링
        embed = discord.Embed(title=":warning: 키워드를 입력해주세요. :pencil:",
                              description="여백의 미를 존중합니다. 하지만 찾을 게 있어서 `!뉴스`를 입력하신거 아닌가요?",
                              color=0x9B0000)
        await ctx.send(embed=embed)
        return

    search_query = keywords # 검색 단어
    url = 'https://openapi.naver.com/v1/search/news.json' # 뉴스에서
    headers = {
        'X-Naver-Client-Id': naver_client_id,
        'X-Naver-Client-Secret': naver_client_secret
    }
    parameters = {
        'query': search_query,  # 검색어 설정
        'display': 3,  # 가져올 뉴스 개수 설정
        'sort': 'sim' # 관련성 높은 기사로 정렬
    }

    try:
        response = requests.get(url, headers=headers, params=parameters) # URL에 Get 요청을 보내서 받아옴
        data = response.json() # JSON 형식 파싱
        articles = data['items'] # 뉴스 기사를 가져옴

        for article in articles: # 각각 제목, 링크를 가져오는데, 이때 beautifulsoup을 사용해 텍스트에 이상한 단어가 들어가지 않도록 한다
            title_html = article['title']
            title_text = BeautifulSoup(title_html, 'html.parser').get_text()
            link = article['link']
            news_info = f"**{title_text}**\n링크: {link}"
            await ctx.send(news_info)

        more_link = f"더 보기: https://search.naver.com/search.naver?where=news&ie=utf8&sm=nws_hty&query={urllib.parse.quote(search_query)}" # 더 보기는 직접 검색어를 넣은 링크를
        await ctx.send(more_link) # 채팅방에 전송해준다

    except Exception as e: # 정보 받아오는데 오류나면 핸들링
        embed = discord.Embed(title=":tools: 읽어오기 오류 발생 :tools:",
                              description="뉴스 정보를 가져오는데 실패하였습니다. 잠시 후 다시 시도해주세요.",
                              color=0x9B0000)
        await ctx.send(embed=embed)

def get_weather(nx, ny): # 날씨 정보 받아오기
    base_url = 'http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst' # 기상청 날씨 정보
    service_key = 'MY_SERVICE_KEY'  # 기상청 날씨 예보 API 서비스 인코딩 된 키. 이것을 사용해야 오류가 안남. 보안 문제로 대체
    #service_key = 'DECODED_KEY'  # 기상청 날씨 예보 API 서비스 키 디코드. 이것을 사용하면 오류가 남. 보안 문제로 대체
    service_key_decoded = urllib.parse.unquote_plus(service_key, encoding='UTF-8') # 인코딩 된 키를 디코딩해서 사용해야함.

    now = datetime.now(timezone('Asia/Seoul')) # 현재 시간(서울 표준시)를 가져옴
    hour = int(now.strftime("%H")) # 몇 시인지 정보를 받아와서

    # 기상청 업데이트 시간에 따라 base_time 설정
    # 기상청 날씨 업데이트는 3시간마다 이루어지고, 혹시라도 누락됐을 경우를 대비해 6시간 이전의 정보를 가져옵니다.
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
    # 단기 예보 1시간 분량의 행이 14개정도 되어서 사용량을 줄이기 위해 14줄만 가져오도록 설정
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
    forecast_data = forecast_response.json() # 정보를 가져와서
    print(forecast_data) # 콘솔창에 결과를 띄워줌
    if forecast_data['response']['header']['resultCode'] == '00':
        # 데이터 반환
        return forecast_data['response']['body']['items']['item']
    else:
        return None
    
@bot.command()
async def 날씨(ctx, *, location=None):
    #thumbnail_url = None # 날씨 사진 초기화
    googlemaps_api_key = 'MY_MAPS_KEY'  # Google Maps API 키, 보안 문제로 대체합니다.
    gmaps = googlemaps.Client(key=googlemaps_api_key)

    if location is None:
        embed = discord.Embed(title=":warning: 지역을 입력해주세요. :mag_right:",
                              description="최소한 `ㅇㅇ시`정도는 입력해주실 수 있으시잖아요~",
                              color=0x9B0000)
        await ctx.send(embed=embed) # 지역명이 없으면 오류 출력
        return
    
    geocode_result = gmaps.geocode(location) # 지오코딩을 통해 지역명에 대한 위도 경도 좌표를 알아온다

    if geocode_result:
        location_data = geocode_result[0]['geometry']['location']
        lat = location_data['lat']  # 위도
        lng = location_data['lng']  # 경도

        nx = lat
        ny = lng

        weather_data = get_weather(nx, ny) # 날씨 정보를 받아온 후
        if weather_data:
            weather_info = ""
            for item in weather_data:
                base_time = item['baseTime']
                if base_time == "2300":
                    fcst_time = "0000"
                else:
                    fcst_time = str(int(base_time) + 100).zfill(4)  # .zfill(4)를 사용하여 항상 4자리 문자열이 되도록 한다. 안 넣으면 2자리 숫자가 아닐때는 오류 발생함
                #print(f"fcst_time: {fcst_time}, item['fcstTime']: {item['fcstTime']}")  # 디버그 목적
                if fcst_time == item['fcstTime']:
                    category = item['category']
                    value = item['fcstValue']
                    # 알맞은 값과 날씨 사진 출력
                    if category == 'TMP':
                        weather_info += f":thermometer: 기온: {value}°C\n"
                    elif category == 'SKY':
                        if value == '1':
                            weather_info += f":white_sun_cloud: 하늘 상태: 맑음\n"
                            thumbnail_url = 'https://ifh.cc/g/NXo1D4.png'
                        elif value == '3': # 자료에 value가 2인 경우가 보이지 않아 넣지 않았습니다.
                            weather_info += f":white_sun_cloud: 하늘 상태: 구름 많음\n"
                            thumbnail_url = 'https://ifh.cc/g/KmH9CA.png'
                        elif value == '4':
                            weather_info += f":white_sun_cloud: 하늘 상태: 흐림\n"
                            thumbnail_url = 'https://ifh.cc/g/fl08Sg.png'
                    elif category == 'PTY':
                        if value == '0':
                            weather_info += f":umbrella2: 강수 형태: 없음\n"
                        elif value == '1':
                            weather_info += f":umbrella2: 강수 형태: 비\n"
                            thumbnail_url = 'https://ifh.cc/g/1kF9f1.png'
                        elif value == '2':
                            weather_info += f":umbrella2: 강수 형태: 비/눈\n"
                            thumbnail_url = 'https://ifh.cc/g/JFkSfT.png'
                        elif value == '3':
                            weather_info += f":umbrella2: 강수 형태: 눈\n"
                            thumbnail_url = 'https://ifh.cc/g/MjPNbt.png'
                        elif value == '4':
                            weather_info += f":umbrella2: 강수 형태: 소나기\n"
                            thumbnail_url = 'https://ifh.cc/g/poJRl5.png'
                    elif category == 'POP':
                        weather_info += f":droplet: 강수 확률: {value}%\n"
                    elif category == 'PCP':
                        if value == '강수없음':
                            weather_info += f":sunny: 1시간 강수량: 강수 없음\n"
                        else:
                            weather_info += f":cloud_rain: 1시간 강수량: {value}mm\n"
                    elif category == 'REH':
                        weather_info += f":sweat_drops: 습도: {value}%\n"
                    elif category == 'TMN':
                        weather_info += f"일 최저 기온: {value}°C\n"
                    elif category == 'TMX':
                        weather_info += f"일 최고 기온: {value}°C\n"

            embed = discord.Embed(title=f"{location}", description=weather_info, color=0x00FFFF)
            embed.set_footer(text="날씨 예보")
            embed.set_thumbnail(url=thumbnail_url)

            await ctx.send(embed=embed)
        else:
            embed1 = discord.Embed(title=":grey_question: 날씨정보 불러오기 오류 :grey_question:",
                                   description="날씨 예보 정보를 가져오는데 실패하였습니다. 잠시 후 다시 시도해주세요.",
                                   color=0x9B0000)
            await ctx.send(embed=embed1)
    else:
        embed2 = discord.Embed(title=":grey_question: 좌표정보 불러오기 오류 :grey_question:",
                               description="좌표 정보를 가져오는데 실패하였습니다. 잠시 후 다시 시도해주세요.",
                               color=0x9B0000)
        await ctx.send(embed=embed2) # 오류들에 대한 핸들링



@bot.event
async def on_voice_state_update(member, before, after): # 콘솔창에 알아볼 수 있도록 상태 출력

    print(f"Voice state update detected for member: {member.name}, Before: {before}, After: {after}")

    # 멤버가 봇이 아니거나 자기 자신이 아니면
    if not member.bot or member != bot.user:
        return

    # 봇이 채널에 들어가는 경우
    if before.channel is None and after.channel is not None:
        print(f"봇이 음성 채널 {after.channel.name}에 입장하였습니다.")

    # 봇이 채널을 나가는 경우
    if before.channel is not None and after.channel is None:
        print(f"봇이 음성 채널 {before.channel.name}에서 퇴장하였습니다.")

    # 봇이 채널을 변경하는 경우
    if before.channel is not None and after.channel is not None:
        print(f"봇이 음성 채널 {before.channel.name}에서 {after.channel.name}로 이동하였습니다.")

bot.run("MY_TOKEN") # 디스코드 봇 토큰. 보안상 대체하였습니다.