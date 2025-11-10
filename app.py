###############################################################################
#  Copyright (C) 2024 LiveTalking@lipku https://github.com/lipku/LiveTalking
#  email: lipku@foxmail.com
# 
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#  
#       http://www.apache.org/licenses/LICENSE-2.0
# 
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
###############################################################################

# server.py
from flask import Flask, render_template,send_from_directory,request, jsonify
from flask_sockets import Sockets
import base64
import time
import json
#import gevent
#from gevent import pywsgi
#from geventwebsocket.handler import WebSocketHandler
import os
import re
import numpy as np
from threading import Thread,Event
#import multiprocessing
import torch.multiprocessing as mp

from aiohttp import web
import aiohttp
import aiohttp_cors
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.rtcrtpsender import RTCRtpSender
from webrtc import HumanPlayer

import argparse
import random

import shutil
import asyncio
import torch

import sys
import web
from aiohttp import web
from aiohttp.web_request import Request
import speech_recognition as sr
from pydub import AudioSegment
from pydub.exceptions import CouldntDecodeError
import wave
import io
import webbrowser

#database
from db import fire_db

#retrival
from retrival import re_and_exc, intent, avatar_text

#kimi
from agent import moonshot_agent

#user
from user import User

#quizapp
from quiz_app import QuizApp


app = Flask(__name__)
#sockets = Sockets(app)
#nerfreals = {}
opt = None
model = None
avatar = None      
lm_model = moonshot_agent()

def remove_special_chars(input_text):
    # 使用正则表达式匹配所有非字母、非数字、非 @ 和 %，以及非标点符号和空格的特殊字符，并替换为空字符串
    # 这里保留汉字、字母、数字、@、%、空格、逗号、句号、. 等标点符号
    cleaned_text = re.sub(r"[^\u4e00-\u9fa5a-zA-Z0-9@%\s.,，。!?;？！：;']+", "", input_text)
    
    return cleaned_text

def count_chinese_and_english(text):
    chinese_count = 0
    english_count = 0

    for char in text:
        if '\u4e00' <= char <= '\u9fa5':
            chinese_count += 1
        elif char.isalpha():
            english_count += 1

    return chinese_count, english_count

def process_input_text(input_text):
    cleaned_text = remove_special_chars(input_text)
    
    # 统计中文和英文的数量
    chinese_count, english_count = count_chinese_and_english(cleaned_text)
    
    # 如果英文占比超过中文，则删除中文
    if english_count > chinese_count:
        # 使用正则表达式删除中文
        cleaned_text = re.sub(r"[\u4e00-\u9fa5]+", "", cleaned_text)
    
    # 检测是否包含 "kimi"，并替换为 "城市大学的AI助手"
    if "kimi" in cleaned_text.lower() and chinese_count > english_count:
        cleaned_text = cleaned_text.replace("Kimi", "城市大学的AI助手")
        cleaned_text = cleaned_text.replace("kimi", "城市大学的AI助手")
    elif "kimi" in cleaned_text.lower() and chinese_count <= english_count:
        cleaned_text = cleaned_text.replace("Kimi", "AI assistant")
        cleaned_text = cleaned_text.replace("kimi", "AI assistant")
    
    # 删除包含 "Moonshot AI" 的句子
    sentences = re.split(r'(?<=[，。！？；：,.;!?])', cleaned_text)  # 按中文标点分割句子
    cleaned_sentences = []
    for sentence in sentences:
        if "Moonshot" not in sentence and "月之暗面" not in sentence and "moonshot" not in sentence and "MoonShot" not in sentence:
            cleaned_sentences.append(sentence)
    cleaned_text = "".join(cleaned_sentences)
    
    return cleaned_text


# def llm_response(message):
#     from llm.LLM import LLM
#     # llm = LLM().init_model('Gemini', model_path= 'gemini-pro',api_key='Your API Key', proxy_url=None)
#     # llm = LLM().init_model('ChatGPT', model_path= 'gpt-3.5-turbo',api_key='Your API Key')
#     llm = LLM().init_model('VllmGPT', model_path= 'THUDM/chatglm3-6b')
#     response = llm.chat(message)
#     print(response)
#     return response

def llm_response(message,nerfreal):
    start = time.perf_counter()
    from openai import OpenAI
    client = OpenAI(
        # 如果您没有配置环境变量，请在此处用您的API Key进行替换
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        # 填写DashScope SDK的base_url
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )
    end = time.perf_counter()
    print(f"llm Time init: {end-start}s")
    completion = client.chat.completions.create(
        model="qwen-plus",
        messages=[{'role': 'system', 'content': 'You are a helpful assistant.'},
                  {'role': 'user', 'content': message}],
        stream=True,
        # 通过以下设置，在流式输出的最后一行展示token使用信息
        stream_options={"include_usage": True}
    )
    result=""
    first = True
    for chunk in completion:
        if len(chunk.choices)>0:
            #print(chunk.choices[0].delta.content)
            if first:
                end = time.perf_counter()
                print(f"llm Time to first chunk: {end-start}s")
                first = False
            msg = chunk.choices[0].delta.content
            lastpos=0
            #msglist = re.split('[,.!;:，。！?]',msg)
            for i, char in enumerate(msg):
                if char in ",.!;:，。！？：；" :
                    result = result+msg[lastpos:i+1]
                    lastpos = i+1
                    if len(result)>10:
                        print(result)
                        #nerfreal.put_msg_txt(result)
                        result=""
            result = result+msg[lastpos:]
    end = time.perf_counter()
    print(f"llm Time to last chunk: {end-start}s")
    #nerfreal.put_msg_txt(result)            

#####webrtc###############################
pcs = set()

def randN(N):
    '''生成长度为 N的随机数 '''
    min = pow(10, N - 1)
    max = pow(10, N)
    return random.randint(min, max - 1)

def build_nerfreal(sessionid):
    opt.sessionid=sessionid
    if opt.model == 'wav2lip':
        from lipreal import LipReal
        nerfreal = LipReal(opt,model,avatar)
    elif opt.model == 'musetalk':
        from musereal import MuseReal
        nerfreal = MuseReal(opt,model,avatar)
    elif opt.model == 'ernerf':
        from nerfreal import NeRFReal
        nerfreal = NeRFReal(opt,model,avatar)
    elif opt.model == 'ultralight':
        from lightreal import LightReal
        nerfreal = LightReal(opt,model,avatar)
    return nerfreal

#@app.route('/offer', methods=['POST'])
async def offer(request):
    params = await request.json()
    offer = RTCSessionDescription(sdp=params["sdp"], type=params["type"])

    """
    if len(nerfreals) >= opt.max_session:
        print('reach max session')
        return -1
    """

    sessionid = randN(6) #len(nerfreals)
    print('sessionid=',sessionid)
    #nerfreals[sessionid] = None
    #nerfreal = await asyncio.get_event_loop().run_in_executor(None, build_nerfreal,sessionid)
    #nerfreals[sessionid] = nerfreal
    
    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print("Connection state is %s" % pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)
            #del nerfreals[sessionid]
        if pc.connectionState == "closed":
            pcs.discard(pc)
            #del nerfreals[sessionid]

    """
    #player = HumanPlayer(nerfreals[sessionid]) #player modification, annotate all player variable
    #audio_sender = pc.addTrack(player.audio)
    #video_sender = pc.addTrack(player.video)
    capabilities = RTCRtpSender.getCapabilities("video")
    preferences = list(filter(lambda x: x.name == "H264", capabilities.codecs))
    preferences += list(filter(lambda x: x.name == "VP8", capabilities.codecs))
    preferences += list(filter(lambda x: x.name == "rtx", capabilities.codecs))
    transceiver = pc.getTransceivers()[1]
    transceiver.setCodecPreferences(preferences)
    """
    
    await pc.setRemoteDescription(offer)

    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    #return jsonify({"sdp": pc.localDescription.sdp, "type": pc.localDescription.type})

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"sdp": pc.localDescription.sdp, "type": pc.localDescription.type, "sessionid":sessionid}
        ),
    )

"""
def _sync_pipeline(input_text, id):
    answer_text = lm_model.answer(input_text)
    nerfreals[id].put_msg_txt(answer_text)
    return answer_text
"""


async def human(request):
    params = await request.json()
    #model = moonshot_agent()
    sessionid = params.get('sessionid',0)
    if params.get('interrupt'):
        #nerfreals[sessionid].flush_talk()
        pass
    if params['type']=='echo':
        print("answer generating!")
        answer_intent = input_intent.route_intent(params['text'])

        """
        if answer_intent == "Learning report":
            avatar_answer = avatar_input.user_answer(params['text'], answer_intent)
            nerfreals[sessionid].put_msg_txt(avatar_answer)
        """
        if answer_intent == "QUIZ":
            # 启动 QuizApp 并获取远程访问URL
            # 在后台启动 QuizApp 服务器
            quiz_url = await asyncio.to_thread(quiz_APP.start_in_background)
            print(f"Quiz system ready at: {quiz_url}")

            # 返回给前端的响应 - 包含Quiz URL
            rae_answer = await asyncio.to_thread(rae.user_answer, params['text'], answer_intent)
            avatar_answer = await asyncio.to_thread(avatar_input.user_answer, rae_answer, answer_intent)
            #nerfreals[sessionid].put_msg_txt(avatar_answer)
            return web.Response(
                content_type="application/json",
                text=json.dumps({
                    "code": 0, 
                    "data": "quiz_started", 
                    "speaking": False, 
                    "reply": rae_answer, 
                    "quiz_url": quiz_url,  # 这是关键 - 前端设备B可以访问的URL
                    "action": "open_quiz"  # 告诉前端需要执行的操作
                }),
            )

        rae_answer = await asyncio.to_thread(rae.user_answer, params['text'], answer_intent)
        avatar_answer = await asyncio.to_thread(avatar_input.user_answer, rae_answer, answer_intent)
        #nerfreals[sessionid].put_msg_txt(avatar_answer)
        print("avatar_answer:", avatar_answer)
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": 0, "data": "ok", "speaking": False, "reply": rae_answer}
            ),
        )


async def humanaudio(request):
    try:
        form= await request.post()
        sessionid = int(form.get('sessionid',0))
        fileobj = form["file"]
        filename=fileobj.filename
        filebytes=fileobj.file.read()
        #nerfreals[sessionid].put_audio_file(filebytes)

        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": 0, "msg":"ok"}
            ),
        )
    except Exception as e:
        return web.Response(
            content_type="application/json",
            text=json.dumps(
                {"code": -1, "msg":"err","data": ""+e.args[0]+""}
            ),
        )
    
async def audio_human(request):
    print("开始进入声音模式！！！！！！！！！")
    content_type = request.content_type  # 获取请求的内容类型
    print("Content-Type:", content_type)
    if content_type.startswith('multipart/form-data'):
        reader = await request.multipart()
        session_id = 0
        text = ""
        params_type = "audio"  # 默认值

        while True:
            part = await reader.next()
            if not part:
                break

            if part.name == 'file':
                # 处理音频文件
                audio_data = await part.read()
                text = await audio_to_text(audio_data)
                print("text is:", text)
            elif part.name == 'sessionid':
                # 提取 sessionid
                session_id_text = await part.text()
                session_id = int(session_id_text) if session_id_text.isdigit() else 0
            elif part.name == 'type':
                # 提取 type
                params_type = await part.text()

        # 模拟 params 字典，传递给现有逻辑
        params = {
            'text': text,
            'sessionid': session_id,
            'type': 'chat'
        }

        print("-----------------------------------------------------------------------------------------------------------------------------------------")
        print("开始进行语言大模型回答！！！！！！！！！")
        
        #answer = lm_model.answer(params['text'])
        if params['text'] == "Could not understand audio":
            #nerfreals[params['sessionid']].put_msg_txt("Sorry, I didn't hear what you said, please try again")
            pass
        else:
            answer = await asyncio.to_thread(lm_model.answer, params['text'])
            clean_answer = process_input_text(answer)
            #nerfreals[params['sessionid']].put_msg_txt(clean_answer)

        return web.json_response({"code": 0, "data": "ok", "sessionid": session_id})

    else:
        # 其他类型的请求处理（如 JSON）
        pass

async def audio_to_text(audio_data):
    try:
        # 将音频数据转换为 PCM WAV 格式
        audio = AudioSegment.from_file(io.BytesIO(audio_data))
        
        # 转换为单声道（mono）并设置采样率为 16 kHz
        audio = audio.set_channels(1).set_frame_rate(16000)
        
        # 导出为 PCM WAV 格式
        audio_io = io.BytesIO()
        audio.export(audio_io, format="wav")
        audio_io.seek(0)  # 重置文件指针

        # 使用 SpeechRecognition 处理音频
        r = sr.Recognizer()
        with sr.AudioFile(audio_io) as source:
            audio = r.record(source)
            try:
                text = text = r.recognize_google(audio, language="zh-CN,en-US")
                return text
            except sr.UnknownValueError:
                return "Could not understand audio"
            except sr.RequestError as e:
                return f"Could not request results from Google Speech Recognition service; {e}"
    except CouldntDecodeError:
        return "Could not decode audio file"
    except Exception as e:
        return f"An error occurred while processing the audio: {str(e)}"

async def set_audiotype(request):
    params = await request.json()

    sessionid = params.get('sessionid',0)    
    #nerfreals[sessionid].set_curr_state(params['audiotype'],params['reinit'])

    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "data":"ok"}
        ),
    )

async def record(request):
    params = await request.json()

    sessionid = params.get('sessionid',0)
    if params['type']=='start_record':
        # nerfreals[sessionid].put_msg_txt(params['text'])
        #nerfreals[sessionid].start_recording()
        pass
    elif params['type']=='end_record':
        #nerfreals[sessionid].stop_recording()
        pass
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "data":"ok"}
        ),
    )

async def is_speaking(request):
    params = await request.json()

    sessionid = params.get('sessionid',0)
    return web.Response(
        content_type="application/json",
        text=json.dumps(
            {"code": 0, "data": nerfreals[sessionid].is_speaking()}
        ),
    )


async def on_shutdown(app):
    # close peer connections
    coros = [pc.close() for pc in pcs]
    await asyncio.gather(*coros)
    pcs.clear()

async def post(url,data):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(url,data=data) as response:
                return await response.text()
    except aiohttp.ClientError as e:
        print(f'Error: {e}')

async def run(push_url,sessionid):
    #nerfreal = await asyncio.get_event_loop().run_in_executor(None, build_nerfreal,sessionid)
    #nerfreals[sessionid] = nerfreal

    pc = RTCPeerConnection()
    pcs.add(pc)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print("Connection state is %s" % pc.connectionState)
        if pc.connectionState == "failed":
            await pc.close()
            pcs.discard(pc)

    #player = HumanPlayer(nerfreals[sessionid])
    #audio_sender = pc.addTrack(player.audio)
    #video_sender = pc.addTrack(player.video)

    await pc.setLocalDescription(await pc.createOffer())
    answer = await post(push_url,pc.localDescription.sdp)
    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer,type='answer'))
##########################################
# os.environ['MKL_SERVICE_FORCE_INTEL'] = '1'
# os.environ['MULTIPROCESSING_METHOD'] = 'forkserver' 


def run_quiz_app():
    """在单独线程中运行 QuizApp"""
    quiz_app.run(port=50012, debug=False, use_reloader=False)


if __name__ == '__main__':
    mp.set_start_method('spawn')
    parser = argparse.ArgumentParser()
    parser.add_argument('--pose', type=str, default="data/anime_a_data/data_kf.json", help="transforms.json, pose source")
    parser.add_argument('--au', type=str, default="data/anime_a_data/au.csv", help="eye blink area")
    parser.add_argument('--ckpt', type=str, default='data/anime_a_data//ngp_kf.pth')
    parser.add_argument('--torso_imgs', type=str, default="", help="torso images path")

    parser.add_argument('-O', action='store_true', help="equals --fp16 --cuda_ray --exp_eye")

    parser.add_argument('--data_range', type=int, nargs='*', default=[0, -1], help="data range to use")
    parser.add_argument('--workspace', type=str, default='data/video')
    parser.add_argument('--seed', type=int, default=0)

    ### training options
   
    parser.add_argument('--num_rays', type=int, default=4096 * 16, help="num rays sampled per image for each training step")
    parser.add_argument('--cuda_ray', action='store_true', help="use CUDA raymarching instead of pytorch")
    parser.add_argument('--max_steps', type=int, default=16, help="max num steps sampled per ray (only valid when using --cuda_ray)")
    parser.add_argument('--num_steps', type=int, default=16, help="num steps sampled per ray (only valid when NOT using --cuda_ray)")
    parser.add_argument('--upsample_steps', type=int, default=0, help="num steps up-sampled per ray (only valid when NOT using --cuda_ray)")
    parser.add_argument('--update_extra_interval', type=int, default=16, help="iter interval to update extra status (only valid when using --cuda_ray)")
    parser.add_argument('--max_ray_batch', type=int, default=4096, help="batch size of rays at inference to avoid OOM (only valid when NOT using --cuda_ray)")

    ### loss set
    parser.add_argument('--warmup_step', type=int, default=10000, help="warm up steps")
    parser.add_argument('--amb_aud_loss', type=int, default=1, help="use ambient aud loss")
    parser.add_argument('--amb_eye_loss', type=int, default=1, help="use ambient eye loss")
    parser.add_argument('--unc_loss', type=int, default=1, help="use uncertainty loss")
    parser.add_argument('--lambda_amb', type=float, default=1e-4, help="lambda for ambient loss")

    ### network backbone options
    parser.add_argument('--fp16', action='store_true', help="use amp mixed precision training")
    
    parser.add_argument('--bg_img', type=str, default='white', help="background image")
    parser.add_argument('--fbg', action='store_true', help="frame-wise bg")
    parser.add_argument('--exp_eye', action='store_true', help="explicitly control the eyes")
    parser.add_argument('--fix_eye', type=float, default=-1, help="fixed eye area, negative to disable, set to 0-0.3 for a reasonable eye")
    parser.add_argument('--smooth_eye', action='store_true', help="smooth the eye area sequence")

    parser.add_argument('--torso_shrink', type=float, default=0.8, help="shrink bg coords to allow more flexibility in deform")

    ### dataset options
    parser.add_argument('--color_space', type=str, default='srgb', help="Color space, supports (linear, srgb)")
    parser.add_argument('--preload', type=int, default=0, help="0 means load data from disk on-the-fly, 1 means preload to CPU, 2 means GPU.")
    # (the default value is for the fox dataset)
    parser.add_argument('--bound', type=float, default=1, help="assume the scene is bounded in box[-bound, bound]^3, if > 1, will invoke adaptive ray marching.")
    parser.add_argument('--scale', type=float, default=4, help="scale camera location into box[-bound, bound]^3")
    parser.add_argument('--offset', type=float, nargs='*', default=[0, 0, 0], help="offset of camera location")
    parser.add_argument('--dt_gamma', type=float, default=1/256, help="dt_gamma (>=0) for adaptive ray marching. set to 0 to disable, >0 to accelerate rendering (but usually with worse quality)")
    parser.add_argument('--min_near', type=float, default=0.05, help="minimum near distance for camera")
    parser.add_argument('--density_thresh', type=float, default=10, help="threshold for density grid to be occupied (sigma)")
    parser.add_argument('--density_thresh_torso', type=float, default=0.01, help="threshold for density grid to be occupied (alpha)")
    parser.add_argument('--patch_size', type=int, default=1, help="[experimental] render patches in training, so as to apply LPIPS loss. 1 means disabled, use [64, 32, 16] to enable")

    parser.add_argument('--init_lips', action='store_true', help="init lips region")
    parser.add_argument('--finetune_lips', action='store_true', help="use LPIPS and landmarks to fine tune lips region")
    parser.add_argument('--smooth_lips', action='store_true', help="smooth the enc_a in a exponential decay way...")

    parser.add_argument('--torso', action='store_true', help="fix head and train torso")
    parser.add_argument('--head_ckpt', type=str, default='', help="head model")

    ### GUI options
    parser.add_argument('--gui', action='store_true', help="start a GUI")
    parser.add_argument('--W', type=int, default=450, help="GUI width")
    parser.add_argument('--H', type=int, default=450, help="GUI height")
    parser.add_argument('--radius', type=float, default=3.35, help="default GUI camera radius from center")
    parser.add_argument('--fovy', type=float, default=21.24, help="default GUI camera fovy")
    parser.add_argument('--max_spp', type=int, default=1, help="GUI rendering max sample per pixel")

    ### else
    parser.add_argument('--att', type=int, default=2, help="audio attention mode (0 = turn off, 1 = left-direction, 2 = bi-direction)")
    parser.add_argument('--aud', type=str, default='', help="audio source (empty will load the default, else should be a path to a npy file)")
    parser.add_argument('--emb', action='store_true', help="use audio class + embedding instead of logits")

    parser.add_argument('--ind_dim', type=int, default=4, help="individual code dim, 0 to turn off")
    parser.add_argument('--ind_num', type=int, default=10000, help="number of individual codes, should be larger than training dataset size")

    parser.add_argument('--ind_dim_torso', type=int, default=8, help="individual code dim, 0 to turn off")

    parser.add_argument('--amb_dim', type=int, default=2, help="ambient dimension")
    parser.add_argument('--part', action='store_true', help="use partial training data (1/10)")
    parser.add_argument('--part2', action='store_true', help="use partial training data (first 15s)")

    parser.add_argument('--train_camera', action='store_true', help="optimize camera pose")
    parser.add_argument('--smooth_path', action='store_true', help="brute-force smooth camera pose trajectory with a window size")
    parser.add_argument('--smooth_path_window', type=int, default=7, help="smoothing window size")

    # asr
    parser.add_argument('--asr', action='store_true', help="load asr for real-time app")
    parser.add_argument('--asr_wav', type=str, default='', help="load the wav and use as input")
    parser.add_argument('--asr_play', action='store_true', help="play out the audio")

    #parser.add_argument('--asr_model', type=str, default='deepspeech')
    parser.add_argument('--asr_model', type=str, default='cpierse/wav2vec2-large-xlsr-53-esperanto') #
    # parser.add_argument('--asr_model', type=str, default='facebook/wav2vec2-large-960h-lv60-self')
    # parser.add_argument('--asr_model', type=str, default='facebook/hubert-large-ls960-ft')

    parser.add_argument('--asr_save_feats', action='store_true')
    # audio FPS
    parser.add_argument('--fps', type=int, default=50)
    # sliding window left-middle-right length (unit: 20ms)
    parser.add_argument('-l', type=int, default=10)
    parser.add_argument('-m', type=int, default=8)
    parser.add_argument('-r', type=int, default=10)

    parser.add_argument('--fullbody', action='store_true', help="fullbody human")
    parser.add_argument('--fullbody_img', type=str, default='data/fullbody/img')
    parser.add_argument('--fullbody_width', type=int, default=580)
    parser.add_argument('--fullbody_height', type=int, default=1080)
    parser.add_argument('--fullbody_offset_x', type=int, default=0)
    parser.add_argument('--fullbody_offset_y', type=int, default=0)

    #musetalk opt
    parser.add_argument('--avatar_id', type=str, default='avator_1')
    parser.add_argument('--bbox_shift', type=int, default=5)
    parser.add_argument('--batch_size', type=int, default=16)

    # parser.add_argument('--customvideo', action='store_true', help="custom video")
    # parser.add_argument('--customvideo_img', type=str, default='data/customvideo/img')
    # parser.add_argument('--customvideo_imgnum', type=int, default=1)

    parser.add_argument('--customvideo_config', type=str, default='')

    parser.add_argument('--tts', type=str, default='edgetts') #xtts gpt-sovits cosyvoice
    parser.add_argument('--REF_FILE', type=str, default=None)
    parser.add_argument('--REF_TEXT', type=str, default=None)
    parser.add_argument('--TTS_SERVER', type=str, default='http://127.0.0.1:9880') # http://localhost:9000
    # parser.add_argument('--CHARACTER', type=str, default='test')
    # parser.add_argument('--EMOTION', type=str, default='default')

    parser.add_argument('--model', type=str, default='ernerf') #musetalk wav2lip

    parser.add_argument('--transport', type=str, default='rtcpush') #rtmp webrtc rtcpush
    parser.add_argument('--push_url', type=str, default='http://localhost:1985/rtc/v1/whip/?app=live&stream=livestream') #rtmp://localhost/live/livestream

    parser.add_argument('--max_session', type=int, default=20)  #multi session count
    parser.add_argument('--listenport', type=int, default=50051)

    opt = parser.parse_args()
    #app.config.from_object(opt)
    #print(app.config)

    #database initialization
    #fdb = fire_db()

    user = User("2", "2", False)
    #retrival and execution initialization
    rae = re_and_exc(user)
    input_intent = intent(user)
    avatar_input = avatar_text(user)
    quiz_APP = QuizApp(user, host='0.0.0.0', port=50012)
    print(f"QuizApp initialized:")
    print(f"  - Server will listen on: 0.0.0.0:{quiz_APP.port}")
    print(f"  - Accessible at: http://{quiz_APP.local_ip}:{quiz_APP.port}")

    opt.customopt = []
    if opt.customvideo_config!='':
        with open(opt.customvideo_config,'r') as file:
            opt.customopt = json.load(file)

    if opt.model == 'ernerf':       
        from nerfreal import NeRFReal,load_model,load_avatar
        model = load_model(opt)
        avatar = load_avatar(opt) 
        
        # we still need test_loader to provide audio features for testing.
        # for k in range(opt.max_session):
        #     opt.sessionid=k
        #     nerfreal = NeRFReal(opt, trainer, test_loader,audio_processor,audio_model)
        #     nerfreals.append(nerfreal)
    elif opt.model == 'musetalk':
        from musereal import MuseReal,load_model,load_avatar,warm_up
        print(opt)
        model = load_model()
        avatar = load_avatar(opt.avatar_id) 
        warm_up(opt.batch_size,model)      
        # for k in range(opt.max_session):
        #     opt.sessionid=k
        #     nerfreal = MuseReal(opt,audio_processor,vae, unet, pe,timesteps)
        #     nerfreals.append(nerfreal)
    elif opt.model == 'wav2lip':
        from lipreal import LipReal,load_model,load_avatar,warm_up
        print(opt)
        model = load_model("./models/wav2lip.pth")
        avatar = load_avatar(opt.avatar_id)
        warm_up(opt.batch_size,model,384)
        # for k in range(opt.max_session):
        #     opt.sessionid=k
        #     nerfreal = LipReal(opt,model)
        #     nerfreals.append(nerfreal)
    elif opt.model == 'ultralight':
        from lightreal import LightReal,load_model,load_avatar,warm_up
        print(opt)
        model = load_model(opt)
        avatar = load_avatar(opt.avatar_id)
        warm_up(opt.batch_size,avatar,160)

    if opt.transport=='rtmp':
        thread_quit = Event()
        #nerfreals[0] = build_nerfreal(0)
        #rendthrd = Thread(target=nerfreals[0].render,args=(thread_quit,))
        rendthrd.start()

    #############################################################################
    appasync = web.Application()
    appasync.on_shutdown.append(on_shutdown)
    appasync.router.add_post("/offer", offer)
    appasync.router.add_post("/human", human)
    appasync.router.add_post("/audio_human", audio_human)
    appasync.router.add_post("/audio_to_text", audio_to_text)
    appasync.router.add_post("/humanaudio", humanaudio)
    appasync.router.add_post("/set_audiotype", set_audiotype)
    appasync.router.add_post("/record", record)
    appasync.router.add_post("/is_speaking", is_speaking)
    appasync.router.add_static('/',path='web')

    # Configure default CORS settings.
    cors = aiohttp_cors.setup(appasync, defaults={
            "*": aiohttp_cors.ResourceOptions(
                allow_credentials=True,
                expose_headers="*",
                allow_headers="*",
            )
        })
    # Configure CORS on all routes.
    for route in list(appasync.router.routes()):
        cors.add(route)

    #pagename='webrtcapi.html'
    pagename='chatapi.html'
    if opt.transport=='rtmp':
        pagename='echoapi.html'
    elif opt.transport=='rtcpush':
        pagename='rtcpushapi.html'
    
    print('start http server; http://<serverip>:'+str(opt.listenport)+'/'+pagename)
    def run_server(runner):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(runner.setup())
        site = web.TCPSite(runner, '0.0.0.0', opt.listenport)
        loop.run_until_complete(site.start())
        if opt.transport=='rtcpush':
            for k in range(opt.max_session):
                push_url = opt.push_url
                if k!=0:
                    push_url = opt.push_url+str(k)
                loop.run_until_complete(run(push_url,k))
        loop.run_forever()    
    #Thread(target=run_server, args=(web.AppRunner(appasync),)).start()
    run_server(web.AppRunner(appasync))

    #app.on_shutdown.append(on_shutdown)
    #app.router.add_post("/offer", offer)
    
    # print('start websocket server')
    # server = pywsgi.WSGIServer(('0.0.0.0', 8000), app, handler_class=WebSocketHandler)
    # server.serve_forever()
    
    
