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
import re
import threading
import queue
import subprocess
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


class SentenceBuffer:
    """
    一个用于处理流式文本并将其重组为完整句子的缓冲区。

    这个类被设计用来解决一个常见问题：当从语言模型（如Gemini）接收流式文本时，
    文本经常在不自然的断点处被分割（例如，在逗号后或句子中间）。
    如果直接将这些片段送入TTS（文本转语音）系统，会导致生成的语音断断续续，听起来非常不自然。

    此类通过以下方式解决该问题：
    1.  **累积文本**: 它有一个内部缓冲区，用于累积传入的文本片段。
    2.  **后台处理**: 一个专用的后台线程持续监控这个缓冲区。
    3.  **句子切分**: 使用正则表达式，它会根据常见的句子结束标点（如。、！、？）来智能地切分文本，形成完整的句子。
    4.  **输出队列**: 切分出的完整句子被放入一个输出队列中，等待消费者（如TTS系统）来获取。
    5.  **生产者-消费者模式**: 它充当了文本流（生产者）和语音合成（消费者）之间的中间件，
        将不规则的文本流转化为规则的、以句子为单位的输出流。

    使用��法:
    -   生产者（例如，Gemini的响应处理程序）调用 `add_text()` 来添加文本片段。
    -   消费者（例如，一个专门的TTS任务处理器）调用 `get_sentence()` 来获取一个完整的句子进行处理。
    -   在对话结束时，调用 `flush()` 来确保缓冲区中剩余的任何文本都被处理。
    -   调用 `stop()` 来安全地终止后台线程。
    """
    def __init__(self):
        self.buffer = ""
        self.sentence_queue = queue.Queue()
        self.lock = threading.Lock()
        self.running = True
        self.processing_thread = threading.Thread(target=self._process_buffer)
        self.processing_thread.daemon = True
        self.processing_thread.start()
        self.logger = logging.getLogger(__name__)

    def add_text(self, text_fragment: str):
        """向缓冲区添加文本片段。"""
        with self.lock:
            self.buffer += text_fragment

    def _process_buffer(self):
        """后台线程，持续处理缓冲区中的文本。"""
        while self.running:
            with self.lock:
                if self.buffer:
                    # 使用正则表达式按标点符号分割句子
                    # 这个正则表达式会在分割后保留分隔符
                    sentences = re.split(r'(。|！|？|……)', self.buffer)
                    
                    # sentences会是这样的列表: ['第一句', '。', '第二句', '！', '']
                    # 我们需要将句子和它的标点重新组合起来
                    processed_text = ""
                    if len(sentences) > 1:
                        # 成对处理句子和它的结束标点
                        for i in range(0, len(sentences) - 1, 2):
                            if i + 1 < len(sentences):
                                sentence = sentences[i]
                                delimiter = sentences[i+1]
                                if sentence and sentence.strip() and delimiter:
                                    full_sentence = sentence + delimiter
                                    self.logger.debug(f"[SENTENCE_BUFFER] 句子入队: '{full_sentence.strip()}'")
                                    self.sentence_queue.put(full_sentence.strip())
                                    processed_text += full_sentence
                        
                        # 更新缓冲区，移除已处理的部分
                        self.buffer = self.buffer[len(processed_text):]
                    
                    # 处理没有标准结尾标点的文本 - 按长度或者特殊情况处理
                    elif self.buffer.strip() and len(self.buffer) > 50:
                        # 如果缓冲区文本较长且没有标准结尾，可能是完整句子
                        self.logger.debug(f"[SENTENCE_BUFFER] 长句子入队: '{self.buffer.strip()}'")
                        self.sentence_queue.put(self.buffer.strip())
                        self.buffer = ""

            time.sleep(0.1)  # 避免CPU空转

    def get_sentence(self, block=True, timeout=None) -> Optional[str]:
        """从队列中获取一个完整的句子。"""
        try:
            return self.sentence_queue.get(block=block, timeout=timeout)
        except queue.Empty:
            return None

    def flush(self):
        """将缓冲区中剩余的任何文本作为最后一个句子推送到队列中。"""
        self.logger.info("Flushing sentence buffer...")
        with self.lock:
            if self.buffer.strip():
                self.sentence_queue.put(self.buffer.strip())
                self.buffer = ""
        self.logger.info("Sentence buffer flushed.")

    def stop(self):
        """停止后台处理线程。"""
        self.logger.info("Stopping sentence buffer...")
        self.running = False
        # 不再需要join，因为daemon线程会随主程序退出
        # self.processing_thread.join()
        self.logger.info("Sentence buffer stopped.")


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
            
            # 本地音频播放
            play_success = await self._play_audio_locally(pcm_file)
            if not play_success:
                self.logger.warning("本地音频播放失败，但合成成功")
            
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
    
    async def _play_audio_locally(self, pcm_file: str) -> bool:
        """使用aplay本地播放PCM音频文件"""
        try:
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                self.executor,
                self._play_audio_sync,
                pcm_file
            )
        except Exception as e:
            self.logger.error(f"本地音频播放错误: {e}")
            return False
    
    def _play_audio_sync(self, pcm_file: str) -> bool:
        """同步播放PCM音频文件"""
        try:
            if not os.path.exists(pcm_file):
                self.logger.error(f"音频文件不存在: {pcm_file}")
                return False
            
            # 使用ffplay播放PCM音频文件 (支持PulseAudio)
            # PCM格式: 16bit, 16kHz, 单声道
            cmd = [
                'ffplay',
                '-f', 's16le',       # 16-bit little-endian format
                '-ar', '16000',      # 16kHz sample rate
                '-ac', '1',          # 单声道
                '-nodisp',           # 不显示视频窗口
                '-autoexit',         # 播放完自动退出
                '-loglevel', 'quiet', # 静默模式
                pcm_file
            ]
            
            self.logger.info(f"播放音频文件: {pcm_file}")
            result = subprocess.run(cmd, capture_output=True, text=True)
            
            if result.returncode == 0:
                self.logger.info("音频播放成功")
                return True
            else:
                self.logger.error(f"ffplay播放失败: {result.stderr}")
                return False
                
        except Exception as e:
            self.logger.error(f"本地音频播放失败: {e}")
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