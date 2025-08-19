# -*- coding:utf-8 -*-
"""
语音合成和播报系统
"""

import os
import time
import logging
import websocket
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


class Speech:
    """语音合成和播放系统"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        os.makedirs(AUDIO_OUTPUT_DIR, exist_ok=True)
        # 合成状态
        self.complete = False
        self.success = False
        self.output_file = None
    
    def _create_ws_url(self):
        """生成WebSocket URL"""
        url = 'wss://tts-api.xfyun.cn/v2/tts'
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))
        
        signature_origin = f"host: ws-api.xfyun.cn\ndate: {date}\nGET /v2/tts HTTP/1.1"
        signature_sha = base64.b64encode(
            hmac.new(TTS_API_SECRET.encode('utf-8'), signature_origin.encode('utf-8'), hashlib.sha256).digest()
        ).decode('utf-8')
        
        authorization = base64.b64encode(
            f'api_key="{TTS_API_KEY}", algorithm="hmac-sha256", headers="host date request-line", signature="{signature_sha}"'.encode('utf-8')
        ).decode('utf-8')
        
        params = {'authorization': authorization, 'date': date, 'host': 'ws-api.xfyun.cn'}
        return url + '?' + urlencode(params)
    
    def _on_message(self, ws, message):
        """WebSocket消息处理"""
        try:
            data = json.loads(message)
            if data.get("code", -1) != 0:
                self.complete = True
                self.success = False
                ws.close()
                return
                
            audio_data = data.get("data", {})
            audio_base64 = audio_data.get("audio", "")
            
            if audio_base64:
                with open(self.output_file, 'ab') as f:
                    f.write(base64.b64decode(audio_base64))
            
            if audio_data.get("status", 0) == 2:  # 最后一帧
                self.complete = True
                self.success = True
                ws.close()
                
        except Exception:
            self.complete = True
            self.success = False
            ws.close()
    
    
    def _on_open(self, ws, text):
        """发送TTS请求"""
        def send_request():
            request_data = {
                "common": {"app_id": TTS_APP_ID},
                "business": {"aue": "raw", "auf": "audio/L16;rate=16000", "vcn": TTS_VOICE, "tte": "utf8"},
                "data": {"status": 2, "text": base64.b64encode(text.encode('utf-8')).decode('utf-8')}
            }
            ws.send(json.dumps(request_data))
        thread.start_new_thread(send_request, ())
    
    def say(self, text: str) -> bool:
        """语音播报"""
        if not text.strip():
            return False
        
        timestamp = int(time.time() * 1000)
        pcm_file = os.path.join(AUDIO_OUTPUT_DIR, f"tts_{timestamp}.pcm")
        
        try:
            # TTS合成
            self.output_file = pcm_file
            self.complete = False
            self.success = False
            
            if os.path.exists(pcm_file):
                os.remove(pcm_file)
            
            ws = websocket.WebSocketApp(
                self._create_ws_url(),
                on_message=self._on_message
            )
            ws.on_open = lambda ws: self._on_open(ws, text)
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
            
            # 等待合成完成
            start_time = time.time()
            while not self.complete and (time.time() - start_time) < 30:
                time.sleep(0.1)
            
            if not self.success:
                return False
            
            # 播放音频
            with open(pcm_file, 'rb') as f:
                audio_data = f.read()
            
            audio_array = np.frombuffer(audio_data, dtype=np.int16).astype(np.float32) / 32768.0
            sd.play(audio_array, samplerate=16000, blocksize=512, blocking=True)
            
            return True
            
        except Exception as e:
            self.logger.error(f"语音播报失败: {e}")
            return False
        finally:
            # 清理临时文件
            if os.path.exists(pcm_file):
                os.remove(pcm_file)


def main():
    """测试语音系统"""
    print("=== 语音系统测试 ===")
    
    speech = Speech()
    test_texts = ["语音系统测试正常", "欢迎使用智能零售机器人", "语音播报功能工作正常"]
    
    for i, text in enumerate(test_texts, 1):
        print(f"\n测试 {i}/{len(test_texts)}: {text}")
        start_time = time.time()
        success = speech.say(text)
        print(f"{'成功' if success else '失败'} (耗时: {time.time() - start_time:.2f}秒)")
        time.sleep(1)
    
    print("\n=== 测试完成 ===")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()