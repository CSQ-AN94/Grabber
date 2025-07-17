# -*- coding:utf-8 -*-
"""
修复版语音合成系统 - 简化队列实现
解决阻塞问题，保持原有功能
"""

import asyncio
import os
import time
import logging
import socket
from typing import Optional, Dict, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
import queue
import threading

# iFlytek WebAPI dependencies
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

# 导入配置系统
try:
    from utils.config import SpeechConfig as ConfigSpeechConfig
except ImportError:
    ConfigSpeechConfig = None

# 全局变量供WebSocket回调使用
current_output_file = None
synthesis_complete = False
synthesis_success = False


@dataclass 
class TTSConfig:
    """TTS引擎内部配置"""
    app_id: str
    api_key: str
    api_secret: str
    voice: str = 'x4_yezi'
    audio_format: str = 'raw'
    sample_rate: int = 16000
    encoding: str = 'utf8'
    output_dir: str = 'intelligence'


class WsParam:
    """WebSocket参数类 - 保持与原iFlytek实现兼容"""
    
    def __init__(self, APPID: str, APIKey: str, APISecret: str, Text: str):
        self.APPID = APPID
        self.APIKey = APIKey
        self.APISecret = APISecret
        self.Text = Text

        # 公共参数(common)
        self.CommonArgs = {"app_id": self.APPID}
        # 业务参数(business)
        self.BusinessArgs = {
            "aue": "raw", 
            "auf": "audio/L16;rate=16000", 
            "vcn": "x4_yezi", 
            "tte": "utf8"
        }
        self.Data = {
            "status": 2, 
            "text": str(base64.b64encode(self.Text.encode('utf-8')), "UTF8")
        }

    def create_url(self) -> str:
        """生成WebSocket连接URL"""
        url = 'wss://tts-api.xfyun.cn/v2/tts'
        # 生成RFC1123格式的时间戳
        now = datetime.now()
        date = format_date_time(mktime(now.timetuple()))

        # 拼接字符串
        signature_origin = "host: " + "ws-api.xfyun.cn" + "\n"
        signature_origin += "date: " + date + "\n"
        signature_origin += "GET " + "/v2/tts " + "HTTP/1.1"
        
        # 进行hmac-sha256进行加密
        signature_sha = hmac.new(
            self.APISecret.encode('utf-8'), 
            signature_origin.encode('utf-8'),
            digestmod=hashlib.sha256
        ).digest()
        signature_sha = base64.b64encode(signature_sha).decode(encoding='utf-8')

        authorization_origin = 'api_key="%s", algorithm="%s", headers="%s", signature="%s"' % (
            self.APIKey, "hmac-sha256", "host date request-line", signature_sha
        )
        authorization = base64.b64encode(authorization_origin.encode('utf-8')).decode(encoding='utf-8')
        
        # 将请求的鉴权参数组合为字典
        v = {
            "authorization": authorization,
            "date": date,
            "host": "ws-api.xfyun.cn"
        }
        # 拼接鉴权参数，生成url
        url = url + '?' + urlencode(v)
        return url


class iFlyTekTTS:
    """iFlytek WebAPI TTS核心实现类"""
    
    def __init__(self, config: TTSConfig):
        self.config = config
        self.logger = logging.getLogger(__name__)
        
    def _create_ws_params(self, text: str) -> WsParam:
        """创建WebSocket参数"""
        return WsParam(
            self.config.app_id,
            self.config.api_key, 
            self.config.api_secret,
            text
        )
    
    async def synthesize_speech(self, text: str, output_file: str) -> bool:
        """
        异步语音合成
        
        Args:
            text: 要合成的文本
            output_file: 输出PCM文件路径
            
        Returns:
            bool: 是否成功
        """
        try:
            # 清理旧文件
            if os.path.exists(output_file):
                os.remove(output_file)
            
            # 创建WebSocket参数
            ws_param = self._create_ws_params(text)
            
            # 在线程池中运行WebSocket连接 (阻塞操作)
            loop = asyncio.get_event_loop()
            success = await loop.run_in_executor(
                None, 
                self._run_websocket_sync, 
                ws_param, 
                output_file
            )
            
            return success and os.path.exists(output_file)
            
        except Exception as e:
            self.logger.error(f"语音合成失败: {e}")
            return False
    
    def _run_websocket_sync(self, ws_param: WsParam, output_file: str) -> bool:
        """同步运行WebSocket连接"""
        try:
            # 设置全局变量供回调使用
            global current_output_file, synthesis_complete, synthesis_success
            current_output_file = output_file
            synthesis_complete = False
            synthesis_success = False
            
            # 配置WebSocket
            websocket.enableTrace(False)
            ws_url = ws_param.create_url()
            ws = websocket.WebSocketApp(
                ws_url,
                on_message=self._on_message,
                on_error=self._on_error,
                on_close=self._on_close
            )
            ws.on_open = lambda ws: self._on_open(ws, ws_param)
            
            # 运行WebSocket
            ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})
            
            # 等待合成完成
            timeout = 30
            start_time = time.time()
            while not synthesis_complete and (time.time() - start_time) < timeout:
                time.sleep(0.1)
            
            return synthesis_success
            
        except Exception as e:
            self.logger.error(f"WebSocket连接错误: {e}")
            return False
    
    def _on_message(self, ws, message):
        """WebSocket消息处理"""
        global current_output_file, synthesis_complete, synthesis_success
        
        try:
            message_data = json.loads(message)
            code = message_data.get("code", -1)
            
            if code != 0:
                error_msg = message_data.get("message", "未知错误")
                self.logger.error(f"TTS API错误: {error_msg} (code: {code})")
                synthesis_complete = True
                synthesis_success = False
                ws.close()
                return
            
            # 获取音频数据
            audio_data = message_data.get("data", {})
            audio_base64 = audio_data.get("audio", "")
            status = audio_data.get("status", 0)
            
            if audio_base64:
                audio_bytes = base64.b64decode(audio_base64)
                with open(current_output_file, 'ab') as f:
                    f.write(audio_bytes)
            
            # 检查是否完成
            if status == 2:  # 最后一帧
                synthesis_complete = True
                synthesis_success = True
                ws.close()
                
        except Exception as e:
            self.logger.error(f"处理TTS响应错误: {e}")
            synthesis_complete = True
            synthesis_success = False
            ws.close()
    
    def _on_error(self, ws, error):
        """WebSocket错误处理"""
        global synthesis_complete, synthesis_success
        self.logger.error(f"WebSocket错误: {error}")
        synthesis_complete = True
        synthesis_success = False
    
    def _on_close(self, ws, close_status_code=None, close_msg=None):
        """WebSocket关闭处理"""
        global synthesis_complete
        synthesis_complete = True
    
    def _on_open(self, ws, ws_param):
        """WebSocket开启处理"""
        def run():
            try:
                request_data = {
                    "common": ws_param.CommonArgs,
                    "business": ws_param.BusinessArgs,
                    "data": ws_param.Data,
                }
                ws.send(json.dumps(request_data))
            except Exception as e:
                self.logger.error(f"发送TTS请求错误: {e}")
                ws.close()
        
        thread.start_new_thread(run, ())


class FixedSpeechSystem:
    """
    修复版语音合成系统
    使用简单的锁机制而不是复杂的队列+线程
    """
    
    def __init__(self, speech_config: Optional[ConfigSpeechConfig] = None):
        self.speech_config = speech_config
        self.logger = logging.getLogger(__name__)
        self.executor = ThreadPoolExecutor(max_workers=2)
        
        # 简单的锁机制防止并发播放
        self.speech_lock = asyncio.Lock()
        
        # 创建TTS配置和引擎
        if self.speech_config:
            # 使用配置文件中的TTS配置
            tts_config = TTSConfig(
                app_id=self.speech_config.app_id,
                api_key=self.speech_config.api_key,
                api_secret=self.speech_config.api_secret
            )
        else:
            # 使用默认配置（向后兼容）
            tts_config = TTSConfig(
                app_id='aeb60378',
                api_key='e248b59b7b21d7291702b7808ba07257',
                api_secret='MjQ1ZmM3MjkwNmEzZTQyN2ZiNTYxN2Ey'
            )
            
        self.tts_engine = iFlyTekTTS(tts_config)
        
        # 确保输出目录存在
        output_dir = 'intelligence'
        os.makedirs(output_dir, exist_ok=True)
        self.output_dir = output_dir
    
    async def say(self, text: str, send_to_speaker: bool = True) -> Dict[str, Any]:
        """
        异步语音合成和网络播放（修复版）
        
        Args:
            text: 要合成的文本
            send_to_speaker: 是否发送到网络扬声器
            
        Returns:
            Dict: 操作结果
        """
        if not text.strip():
            return {"success": False, "message": "文本为空"}
        
        # 使用锁确保顺序播放
        async with self.speech_lock:
            try:
                # 生成唯一的文件名
                timestamp = int(time.time() * 1000)
                pcm_file = os.path.join(self.output_dir, f"tts_{timestamp}.pcm")
                
                self.logger.info(f"开始合成语音: {text}")
                
                # 异步语音合成
                success = await self.tts_engine.synthesize_speech(text, pcm_file)
                
                if not success:
                    self.logger.error("语音合成失败")
                    return {"success": False, "message": "语音合成失败"}
                
                self.logger.info("语音合成成功，开始发送到扬声器")
                
                # 发送音频到网络扬声器
                if send_to_speaker and self.speech_config:
                    send_success = await self._send_audio_to_speaker(pcm_file)
                    if not send_success:
                        self.logger.warning("网络音频发送失败，但合成成功")
                        # 即使网络发送失败，仍然返回成功（因为合成成功了）
                elif send_to_speaker and not self.speech_config:
                    self.logger.warning("缺少语音配置，跳过网络音频发送")
                
                # 清理临时文件
                self._cleanup_files([pcm_file])
                
                self.logger.info(f"语音处理完成: {text}")
                return {
                    "success": True,
                    "message": "语音合成和发送完成",
                    "text": text
                }
                
            except Exception as e:
                self.logger.error(f"语音合成系统错误: {e}")
                return {"success": False, "message": f"系统错误: {str(e)}"}
    
    async def _send_audio_to_speaker(self, pcm_file: str) -> bool:
        """发送音频到网络扬声器"""
        if not self.speech_config:
            self.logger.error("缺少语音配置，无法发送网络音频")
            return False
            
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                self.executor,
                self._send_audio_sync,
                pcm_file
            )
        except Exception as e:
            self.logger.error(f"网络音频发送错误: {e}")
            return False
    
    def _send_audio_sync(self, pcm_file: str) -> bool:
        """同步发送音频到网络扬声器"""
        try:
            # 读取PCM音频数据
            with open(pcm_file, 'rb') as f:
                audio_data = f.read()
            
            if not audio_data:
                self.logger.error("音频文件为空")
                return False
            
            # 连接到笔记本扬声器服务器
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(10)  # 10秒超时
            
            try:
                self.logger.info(f"尝试连接到扬声器服务器: {self.speech_config.notebook_ip}:{self.speech_config.speaker_port}")
                sock.connect((self.speech_config.notebook_ip, self.speech_config.speaker_port))
                self.logger.info("成功连接到扬声器服务器")
                
                # 发送音频数据
                sock.sendall(audio_data)
                self.logger.info(f"成功发送音频数据: {len(audio_data)} 字节")
                
                return True
                
            finally:
                sock.close()
                
        except ConnectionRefusedError:
            self.logger.error(f"连接被拒绝: {self.speech_config.notebook_ip}:{self.speech_config.speaker_port} - 扬声器服务器可能未启动")
            return False
        except socket.timeout:
            self.logger.error("连接超时 - 检查网络连接和扬声器服务器状态")
            return False
        except Exception as e:
            self.logger.error(f"网络音频发送失败: {e}")
            return False
    
    def _cleanup_files(self, files: list):
        """清理临时文件"""
        for file_path in files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                self.logger.warning(f"清理文件失败 {file_path}: {e}")
    
    async def test_speech(self, test_text: str = "语音合成系统测试正常") -> Dict[str, Any]:
        """测试语音合成系统"""
        self.logger.info("开始语音系统测试")
        result = await self.say(test_text)
        self.logger.info(f"语音系统测试结果: {result}")
        return result
    
    def stop_speech_system(self):
        """停止语音系统"""
        self.logger.info("停止语音系统...")
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)
    
    def __del__(self):
        """清理资源"""
        try:
            self.stop_speech_system()
        except:
            pass


# 测试功能
async def test_fixed_speech_system(speech_config: Optional[ConfigSpeechConfig] = None):
    """测试修复版语音系统"""
    print("🎤 测试修复版语音合成系统...")
    
    # 使用配置创建语音系统
    speech_system = FixedSpeechSystem(speech_config)
    
    # 测试基本功能
    test_texts = [
        "第一条语音测试",
        "第二条语音测试",
        "第三条语音测试"
    ]
    
    for i, text in enumerate(test_texts, 1):
        print(f"\n测试 {i}/{len(test_texts)}: {text}")
        start_time = time.time()
        result = await speech_system.say(text)
        end_time = time.time()
        print(f"结果: {result}")
        print(f"耗时: {end_time - start_time:.2f}秒")
        
        if result["success"]:
            print("✅ 成功")
        else:
            print(f"❌ 失败: {result['message']}")
    
    print("\n🎤 修复版语音系统测试完成")


if __name__ == "__main__":
    # 如果直接运行此文件，则启动测试
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        # 测试模式 - 尝试加载配置
        try:
            from utils.config import load_config
            config = load_config("config.ini")
            speech_config = config.speech
            print("使用配置文件中的语音配置")
        except Exception as e:
            print(f"加载配置失败，使用默认配置: {e}")
            speech_config = None
        
        asyncio.run(test_fixed_speech_system(speech_config))
    else:
        print("修复版智能语音合成系统")
        print("使用方法:")
        print("  python speech_fixed.py test     - 测试语音合成")
        print("  或在代码中导入FixedSpeechSystem类使用")