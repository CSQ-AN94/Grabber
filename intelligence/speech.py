# intelligence/speech.py
import openai
import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
import io
import os
import subprocess

class SpeechSystem:
    """
    封装了语音识别(ASR)和语音合成(TTS)的功能。
    使用OpenAI API以获得高质量的结果和简单的实现。
    """
    def __init__(self, speech_config):
        """
        初始化时，设置OpenAI的API密钥。
        """
        # 确保你的API密钥已经设置在环境变量或配置文件中
        self.client = openai.OpenAI(api_key=speech_config.openai_api_key)
        self.sample_rate = 16000  # 16kHz，这是Whisper ASR的标准采样率
        self.channels = 1         # 单声道

    def say(self, text: str):
        """
        【语音合成 TTS】
        接收文本，将其转换为语音并立即播放。
        """
        print(f"[Speech] Saying: '{text}'")
        try:
            # 1. 调用OpenAI TTS-1模型API，生成语音数据
            # response.content 中包含了mp3格式的音频二进制数据
            response = self.client.audio.speech.create(
                model="tts-1",
                voice="alloy", # 'alloy'是一个听起来很舒服的通用声音
                input=text
            )

            # 2. 使用ffplay播放音频流，无需保存为文件
            # 这是一种高效、低延迟的播放方式
            # -i -: 从标准输入读取数据
            # -autoexit: 播放完毕后自动退出
            # -nodisp: 不显示任何GUI窗口
            ffplay_process = subprocess.Popen(
                ["ffplay", "-autoexit", "-nodisp", "-i", "-"],
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            # 将API返回的音频数据写入ffplay的管道
            ffplay_process.communicate(input=response.content)

        except Exception as e:
            print(f"[Speech] ERROR during text-to-speech: {e}")

    def listen(self, duration: int = 5) -> str:
        """
        【语音识别 ASR】
        录制指定时长的音频，调用Whisper API进行识别，并返回文本。
        """
        print(f"[Speech] Listening for {duration} seconds...")
        try:
            # 1. 使用sounddevice录制音频
            # sd.rec会立即返回，录音在后台进行
            recording = sd.rec(int(duration * self.sample_rate), samplerate=self.sample_rate, channels=self.channels, dtype='int16')
            sd.wait()  # 等待录音完成

            # 2. 将录音数据（Numpy数组）转换为WAV格式的内存中的文件
            wav_buffer = io.BytesIO()
            wav.write(wav_buffer, self.sample_rate, recording)
            wav_buffer.seek(0) # 重置指针到文件开头
            
            # 将内存中的文件伪装成一个真实文件，以便API上传
            wav_buffer.name = 'recording.wav'

            # 3. 调用OpenAI Whisper-1模型API，进行语音识别
            transcription = self.client.audio.transcriptions.create(
                model="whisper-1",
                file=wav_buffer,
                response_format="text"
            )
            
            print(f"[Speech] Heard: '{transcription}'")
            return transcription

        except Exception as e:
            print(f"[Speech] ERROR during speech-to-text: {e}")
            return ""