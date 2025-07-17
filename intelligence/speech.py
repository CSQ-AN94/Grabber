# -*- coding:utf-8 -*-
"""
智能语音合成系统 - 基于iFlytek WebAPI
提供清洁的异步接口给Agent使用，支持网络音频输出

重构自原始iFlytek demo，优化为生产级别的模块化设计
支持配置文件管理和网络音频传输
"""

import asyncio
import os
import time
import logging
# import socket  # 移除网络依赖
# import wave  # 移除wave依赖
from typing import Optional, Dict, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
# import queue  # 移除队列依赖
# import threading  # 移除线程依赖

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


class SpeechSystem:
    """
    高级语音合成系统 - 优化版
    为Agent提供简洁的异步语音合成接口
    支持网络音频输出到远程扬声器
    具有队列管理防止语音重叠
    """
    
    def __init__(self, speech_config: Optional[ConfigSpeechConfig] = None):
        self.speech_config = speech_config
        self.logger = logging.getLogger(__name__)
        self.executor = ThreadPoolExecutor(max_workers=2)
        
        # 语音播放队列和管理
        self.speech_queue = queue.Queue(maxsize=5)  # 限制队列大小
        self.speech_worker_running = False
        self.speech_worker_thread = None
        self.current_speech_task = None
        self.speech_lock = threading.Lock()
        
        # 启动语音播放工作线程
        self._start_speech_worker()
        
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
    
    def _start_speech_worker(self):
        """启动语音播放工作线程"""
        if not self.speech_worker_running:
            self.speech_worker_running = True
            self.speech_worker_thread = threading.Thread(target=self._speech_worker)
            self.speech_worker_thread.daemon = True
            self.speech_worker_thread.start()
            self.logger.info("🎵 语音播放工作线程已启动")
    
    def _speech_worker(self):
        """语音播放工作线程"""
        while self.speech_worker_running:
            try:
                # 从队列获取语音任务
                task = self.speech_queue.get(timeout=1.0)
                
                if task is None:  # 停止信号
                    break
                    
                text, future = task
                self.current_speech_task = task
                
                # 执行语音合成和播放
                try:
                    result = asyncio.run(self._synthesize_and_play(text))
                    if not future.cancelled():
                        future.set_result(result)
                except Exception as e:
                    if not future.cancelled():
                        future.set_exception(e)
                finally:
                    self.current_speech_task = None
                    self.speech_queue.task_done()
                    
            except queue.Empty:
                continue
            except Exception as e:
                self.logger.error(f"语音工作线程错误: {e}")
                
        self.logger.info("🎵 语音播放工作线程已停止")
    
    def _stop_speech_worker(self):
        """停止语音播放工作线程"""
        if self.speech_worker_running:
            self.speech_worker_running = False
            
            # 清空队列
            while not self.speech_queue.empty():
                try:
                    task = self.speech_queue.get_nowait()
                    if task and len(task) == 2:
                        _, future = task
                        if not future.cancelled():
                            future.cancel()
                except queue.Empty:
                    break
            
            # 发送停止信号
            try:
                self.speech_queue.put(None, timeout=1.0)
            except queue.Full:
                pass
            
            # 等待线程结束
            if self.speech_worker_thread and self.speech_worker_thread.is_alive():
                self.speech_worker_thread.join(timeout=3.0)
                if self.speech_worker_thread.is_alive():
                    self.logger.warning("语音工作线程未能正常结束")
    
    async def say(self, text: str, send_to_speaker: bool = True, interrupt_current: bool = False) -> Dict[str, Any]:
        """
        异步语音合成和网络播放（优化版）
        
        Args:
            text: 要合成的文本
            send_to_speaker: 是否发送到网络扬声器
            interrupt_current: 是否中断当前播放
            
        Returns:
            Dict: 操作结果
        """
        if not text.strip():
            return {"success": False, "message": "文本为空"}
        
        # 如果要求中断当前播放，清空队列
        if interrupt_current:
            self._clear_speech_queue()
        
        # 如果队列满了，丢弃最旧的任务
        if self.speech_queue.full():
            try:
                old_task = self.speech_queue.get_nowait()
                if old_task and len(old_task) == 2:
                    _, old_future = old_task
                    if not old_future.cancelled():
                        old_future.cancel()
                self.logger.warning("语音队列满，丢弃旧任务")
            except queue.Empty:
                pass
        
        # 创建Future对象用于异步等待结果
        future = asyncio.Future()
        
        try:
            # 将任务加入队列
            self.speech_queue.put((text, future), block=False)
            
            # 等待任务完成
            result = await future
            return result
            
        except queue.Full:
            return {"success": False, "message": "语音队列满，请稍后再试"}
        except asyncio.CancelledError:
            return {"success": False, "message": "语音任务被取消"}
        except Exception as e:
            self.logger.error(f"语音合成错误: {e}")
            return {"success": False, "message": f"系统错误: {str(e)}"}
    
    def _clear_speech_queue(self):
        """清空语音队列"""
        with self.speech_lock:
            while not self.speech_queue.empty():
                try:
                    task = self.speech_queue.get_nowait()
                    if task and len(task) == 2:
                        _, future = task
                        if not future.cancelled():
                            future.cancel()
                except queue.Empty:
                    break
            self.logger.info("语音队列已清空")
    
    async def _synthesize_and_play(self, text: str) -> Dict[str, Any]:
        """
        实际的语音合成和播放逻辑
        
        Args:
            text: 要合成的文本
            
        Returns:
            Dict: 操作结果
        """
        try:
            # 生成唯一的文件名
            timestamp = int(time.time() * 1000)
            pcm_file = os.path.join(self.output_dir, f"tts_{timestamp}.pcm")
            
            self.logger.info(f"开始合成语音: {text}")
            
            # 异步语音合成
            success = await self.tts_engine.synthesize_speech(text, pcm_file)
            
            if not success:
                return {"success": False, "message": "语音合成失败"}
            
            # 发送音频到网络扬声器
            if self.speech_config:
                send_success = await self._send_audio_to_speaker(pcm_file)
                if not send_success:
                    self.logger.warning("网络音频发送失败，但合成成功")
            else:
                self.logger.warning("缺少语音配置，跳过网络音频发送")
            
            # 清理临时文件
            self._cleanup_files([pcm_file])
            
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
        """同步发送音频到网络扬声器（优化版）"""
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
                
                # 分块发送音频数据以避免网络拥堵
                chunk_size = 4096
                bytes_sent = 0
                
                while bytes_sent < len(audio_data):
                    chunk = audio_data[bytes_sent:bytes_sent + chunk_size]
                    sock.sendall(chunk)
                    bytes_sent += len(chunk)
                    
                    # 小延迟避免网络拥堵
                    if bytes_sent < len(audio_data):
                        time.sleep(0.001)  # 1ms延迟
                
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
        self._stop_speech_worker()
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)
    
    def __del__(self):
        """清理资源"""
        try:
            self.stop_speech_system()
        except:
            pass


# 测试功能
async def test_speech_system(speech_config: Optional[ConfigSpeechConfig] = None):
    """测试语音系统"""
    print("🎤 测试语音合成系统...")
    
    # 使用配置创建语音系统
    speech_system = SpeechSystem(speech_config)
    
    # 测试基本功能
    test_texts = [
        "语音合成系统测试正常",
        "欢迎使用智慧零售机器人助手",
        "语音播放功能工作正常"
    ]
    
    for i, text in enumerate(test_texts, 1):
        print(f"\n测试 {i}/{len(test_texts)}: {text}")
        result = await speech_system.say(text)
        print(f"结果: {result}")
        
        if result["success"]:
            print("✅ 成功")
        else:
            print(f"❌ 失败: {result['message']}")
        
        # 等待一下再继续
        await asyncio.sleep(1)
    
    print("\n🎤 语音系统测试完成")


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
        
        asyncio.run(test_speech_system(speech_config))
    else:
        print("智能语音合成系统")
        print("使用方法:")
        print("  python speech.py test     - 测试语音合成")
        print("  或在代码中导入SpeechSystem类使用")