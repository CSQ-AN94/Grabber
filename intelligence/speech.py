# -*- coding:utf-8 -*-
"""
语音合成和播报系统
"""

import os
import time
import logging
import websocket
import datetime
import hashlib
import base64
import hmac
import json
from urllib.parse import urlencode
import ssl
from wsgiref.handlers import format_date_time
from datetime import datetime
from time import mktime
import _thread as thread
import sounddevice as sd
import numpy as np


# TTS配置
TTS_APP_ID = 'aeb60378'
TTS_API_KEY = 'e248b59b7b21d7291702b7808ba07257'
TTS_API_SECRET = 'MjQ1ZmM3MjkwNmEzZTQyN2ZiNTYxN2Ey'
TTS_VOICE = 'x4_yezi'
AUDIO_OUTPUT_DIR = 'intelligence/audio_temp'

# 硬编码音频环境变量。 换设备可能要修改
os.environ.update({
    'PULSE_RUNTIME_PATH': '/run/user/1000/pulse',
    'PULSE_SERVER': 'unix:/run/user/1000/pulse/native',
    'XDG_RUNTIME_DIR': '/run/user/1000'
})

# 全局状态
_synthesis_complete = False
_synthesis_success = False
_output_file = None


def _create_ws_url(app_id: str, api_key: str, api_secret: str) -> str:
    """生成WebSocket URL"""
    url = 'wss://tts-api.xfyun.cn/v2/tts'
    now = datetime.now()
    date = format_date_time(mktime(now.timetuple()))
    
    signature_origin = f"host: ws-api.xfyun.cn\ndate: {date}\nGET /v2/tts HTTP/1.1"
    signature_sha = base64.b64encode(
        hmac.new(api_secret.encode('utf-8'), signature_origin.encode('utf-8'), hashlib.sha256).digest()
    ).decode('utf-8')
    
    authorization = base64.b64encode(
        f'api_key="{api_key}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha}"'.encode('utf-8')
    ).decode('utf-8')
    
    params = {'authorization': authorization, 'date': date, 'host': 'ws-api.xfyun.cn'}
    return url + '?' + urlencode(params)


def _on_message(ws, message):
    """WebSocket消息处理"""
    global _synthesis_complete, _synthesis_success, _output_file
    
    try:
        data = json.loads(message)
        if data.get("code", -1) != 0:
            _synthesis_complete = True
            _synthesis_success = False
            ws.close()
            return
            
        audio_data = data.get("data", {})
        audio_base64 = audio_data.get("audio", "")
        
        if audio_base64:
            audio_bytes = base64.b64decode(audio_base64)
            with open(_output_file, 'ab') as f:
                f.write(audio_bytes)
        
        if audio_data.get("status", 0) == 2:  # 最后一帧
            _synthesis_complete = True
            _synthesis_success = True
            ws.close()
            
    except Exception:
        _synthesis_complete = True
        _synthesis_success = False
        ws.close()


def _on_error(ws, error):
    """WebSocket错误处理"""
    global _synthesis_complete, _synthesis_success
    _synthesis_complete = True
    _synthesis_success = False


def _on_close(ws, close_status_code=None, close_msg=None):
    """WebSocket关闭处理"""
    global _synthesis_complete
    _synthesis_complete = True


def _on_open(ws, text):
    """WebSocket开启处理"""
    def run():
        request_data = {
            "common": {"app_id": TTS_APP_ID},
            "business": {"aue": "raw", "auf": "audio/L16;rate=16000", "vcn": TTS_VOICE, "tte": "utf8"},
            "data": {"status": 2, "text": base64.b64encode(text.encode('utf-8')).decode('utf-8')}
        }
        ws.send(json.dumps(request_data))
    thread.start_new_thread(run, ())


def _synthesize_tts(text: str, output_file: str) -> bool:
    """TTS合成"""
    global _synthesis_complete, _synthesis_success, _output_file
    
    _output_file = output_file
    _synthesis_complete = False
    _synthesis_success = False
    
    if os.path.exists(output_file):
        os.remove(output_file)
    
    try:
        ws_url = _create_ws_url(TTS_APP_ID, TTS_API_KEY, TTS_API_SECRET)
        ws = websocket.WebSocketApp(
            ws_url,
            on_message=_on_message,
            on_error=_on_error,
            on_close=_on_close
        )
        ws.on_open = lambda ws: _on_open(ws, text)
        ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
        
        # 等待完成
        timeout = 30
        start_time = time.time()
        while not _synthesis_complete and (time.time() - start_time) < timeout:
            time.sleep(0.1)
            
        return _synthesis_success
    except Exception:
        return False


def _play_audio(pcm_file: str) -> bool:
    """播放音频"""
    # try:
    #     # 优先使用aplay
    #     import subprocess
    #     result = subprocess.run(
    #         ['aplay', '-t', 'raw', '-f', 'S16_LE', '-r', '16000', '-c', '1', pcm_file],
    #         capture_output=True, timeout=10
    #     )
    #     if result.returncode == 0:
    #         return True
    # except Exception:
    #     pass
    
    try:
        # 回退到sounddevice
        with open(pcm_file, 'rb') as f:
            audio_data = f.read()
        
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        audio_float = audio_array.astype(np.float32) / 32768.0
        
        sd.play(audio_float, samplerate=16000, blocking=True)
        return True
    except Exception:
        return False


class Speech:
    """简化语音系统"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        os.makedirs(AUDIO_OUTPUT_DIR, exist_ok=True)
    
    def say(self, text: str) -> bool:
        """语音播报"""
        if not text.strip():
            return False
        
        # 生成临时文件
        timestamp = int(time.time() * 1000)
        pcm_file = os.path.join(AUDIO_OUTPUT_DIR, f"tts_{timestamp}.pcm")
        
        try:
            # TTS合成
            if not _synthesize_tts(text, pcm_file):
                return False
            
            # 播放音频
            success = _play_audio(pcm_file)
            
            # 清理文件
            if os.path.exists(pcm_file):
                os.remove(pcm_file)
            
            return success
        except Exception as e:
            self.logger.error(f"语音播报失败: {e}")
            return False


def main():
    """测试语音系统"""
    print("=== 语音系统测试 ===")
    
    speech = Speech()
    
    test_texts = [
        "语音系统测试正常",
        "欢迎使用智能零售机器人",
        "语音播报功能工作正常"
    ]
    
    for i, text in enumerate(test_texts, 1):
        print(f"\n测试 {i}/{len(test_texts)}: {text}")
        start_time = time.time()
        success = speech.say(text)
        end_time = time.time()
        
        if success:
            print(f"成功 (耗时: {end_time - start_time:.2f}秒)")
        else:
            print("失败")
        
        time.sleep(1)
    
    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()