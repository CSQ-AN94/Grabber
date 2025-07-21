# -*- coding:utf-8 -*-
"""
本地语音合成系统 - 简化版
基于iFlyTek WebAPI的TTS功能，支持本地音频播放
移除了所有网络音频传输相关代码
"""

import asyncio
import os
import time
import logging
from typing import Optional, Dict, Any
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor

# iFlyTek WebAPI dependencies
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

# 本地音频播放依赖
import sounddevice as sd
import numpy as np

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


class LocalAudioPlayer:
    """本地音频播放器"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self._configure_audio_devices()
    
    def _configure_audio_devices(self):
        """配置音频设备和采样率"""
        try:
            # 首先检查环境变量是否强制指定了设备
            force_device = os.environ.get('GRABBER_AUDIO_DEVICE')
            if force_device:
                self.logger.info(f"环境变量强制指定音频设备: {force_device}")
                if force_device.lower() == 'pulse':
                    return self._configure_pulse_audio()
            
            # 检查是否在Docker容器中
            is_docker = os.path.exists('/.dockerenv') or os.environ.get('DOCKER_ENV') == 'true'
            if is_docker:
                self.logger.info("检测到Docker环境，尝试PulseAudio配置")
                if self._configure_pulse_audio():
                    return
            
            # 回退到原有的设备检测逻辑
            self._configure_sounddevice_audio()
            
        except Exception as e:
            self.logger.error(f"配置音频设备失败: {e}")
            self.output_device = sd.default.device[1]
            self.output_sample_rate = 44100
    
    def _configure_pulse_audio(self):
        """配置PulseAudio直接播放"""
        try:
            # 设置PulseAudio环境变量
            os.environ['PULSE_RUNTIME_PATH'] = '/run/user/1000/pulse'
            os.environ['PULSE_SERVER'] = 'unix:/run/user/1000/pulse/native'
            os.environ['XDG_RUNTIME_DIR'] = '/run/user/1000'
            
            # 检查PulseAudio socket
            socket_path = '/run/user/1000/pulse/native'
            if not os.path.exists(socket_path):
                self.logger.warning("PulseAudio socket不存在，回退到sounddevice")
                return False
            
            # 设置使用PulseAudio
            self.output_device = 'pulse'
            self.output_sample_rate = 44100
            self.use_pulseaudio = True
            
            self.logger.info("配置PulseAudio直接播放成功")
            return True
            
        except Exception as e:
            self.logger.error(f"配置PulseAudio失败: {e}")
            return False
    
    def _configure_sounddevice_audio(self):
        """配置sounddevice音频设备"""
        devices = sd.query_devices()
        
        # 设备优先级顺序：优先选择非HDMI设备
        device_priorities = [
            # 1. 优先：pulse和default设备（宿主机可用）
            ("pulse", 44100),
            ("default", 44100),
            # 2. 其次：sof-hda-dsp设备（主扬声器）
            ("sof-hda-dsp", 48000),
            # 3. 最后：HDMI设备（可能没有音频输出）
            ("HDA NVidia: HDMI", 44100),
        ]
        
        best_output_device = None
        best_output_rate = None
        
        # 按优先级搜索设备
        for device_name_pattern, preferred_rate in device_priorities:
            for device_id, device in enumerate(devices):
                if (device['max_output_channels'] > 0 and 
                    device_name_pattern in device['name']):
                    
                    # 测试支持的采样率
                    test_rates = [preferred_rate, 44100, 48000]
                    for sample_rate in test_rates:
                        try:
                            sd.check_output_settings(device=device_id, samplerate=sample_rate)
                            best_output_device = device_id
                            best_output_rate = sample_rate
                            self.logger.info(f"选择输出设备: [{device_id}] {device['name']} @ {sample_rate}Hz")
                            break
                        except:
                            continue
                    
                    if best_output_device is not None:
                        break
            
            if best_output_device is not None:
                break
        
        # 如果没有找到合适的设备，使用默认设备
        if best_output_device is None:
            self.logger.warning("未找到合适的输出设备，使用默认设备")
            best_output_device = sd.default.device[1]
            best_output_rate = 44100
        
        self.output_device = best_output_device
        self.output_sample_rate = best_output_rate
        self.use_pulseaudio = False
    
    def play_pcm_file_sync(self, pcm_file: str) -> bool:
        """播放PCM音频文件"""
        try:
            # 如果配置了PulseAudio，优先使用PulseAudio播放
            if hasattr(self, 'use_pulseaudio') and self.use_pulseaudio:
                return self._play_with_pulseaudio(pcm_file)
            
            # 读取PCM文件
            with open(pcm_file, 'rb') as f:
                audio_data = f.read()
            
            if not audio_data:
                self.logger.error("音频文件为空")
                return False
            
            # 转换为numpy数组
            audio_array = np.frombuffer(audio_data, dtype=np.int16)
            
            if len(audio_array) == 0:
                self.logger.error("音频数据为空")
                return False
            
            # 转换为float32格式 (sounddevice要求)
            audio_float = audio_array.astype(np.float32) / 32768.0
            
            # 如果需要重采样（从16000Hz到输出设备支持的采样率）
            if self.output_sample_rate != 16000:
                audio_float = self._resample_audio(audio_float, 16000, self.output_sample_rate)
            
            # 首先尝试sounddevice播放
            try:
                sd.play(audio_float, samplerate=self.output_sample_rate, device=self.output_device, blocking=True)
                self.logger.info(f"成功播放音频: {len(audio_data)} 字节")
                return True
            except Exception as e:
                self.logger.warning(f"sounddevice播放失败: {e}")
                # 如果sounddevice失败，尝试命令行播放
                return self._play_with_command_line(pcm_file)
            
        except Exception as e:
            self.logger.error(f"播放音频失败: {e}")
            return False
    
    def _play_with_pulseaudio(self, pcm_file: str) -> bool:
        """使用PulseAudio播放PCM文件"""
        try:
            import subprocess
            
            # 获取音频文件信息用于超时设置
            file_size = os.path.getsize(pcm_file)
            expected_duration = file_size / (16000 * 2)  # 16kHz, 16-bit
            
            # 设置PulseAudio环境变量
            env = os.environ.copy()
            env.update({
                'PULSE_RUNTIME_PATH': '/run/user/1000/pulse',
                'PULSE_SERVER': 'unix:/run/user/1000/pulse/native',
                'XDG_RUNTIME_DIR': '/run/user/1000',
            })
            
            # 使用aplay直接播放，确保真正等待播放完成
            try:
                aplay_cmd = [
                    'aplay', '-t', 'raw', '-f', 'S16_LE', '-r', '16000', '-c', '1', pcm_file
                ]
                
                result = subprocess.run(aplay_cmd, capture_output=True, text=True, 
                                      env=env, timeout=expected_duration + 5)
                
                if result.returncode == 0:
                    self.logger.info("aplay播放成功")
                    return True
                else:
                    self.logger.warning(f"aplay播放失败: {result.stderr}")
                    
            except subprocess.TimeoutExpired:
                self.logger.error("aplay播放超时")
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                self.logger.warning(f"aplay错误: {e}")
            
            # 如果aplay失败，尝试ffplay (阻塞播放)
            try:
                ffplay_cmd = [
                    'ffplay', '-nodisp', '-autoexit', '-f', 's16le', '-ar', '16000', '-ac', '1', pcm_file
                ]
                
                result = subprocess.run(ffplay_cmd, capture_output=True, text=True, 
                                      env=env, timeout=expected_duration + 5)
                
                if result.returncode == 0:
                    self.logger.info("ffplay播放成功")
                    return True
                else:
                    self.logger.warning(f"ffplay播放失败: {result.stderr}")
                    
            except subprocess.TimeoutExpired:
                self.logger.error("ffplay播放超时")
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                self.logger.warning(f"ffplay错误: {e}")
            
            # 回退到命令行播放
            return self._play_with_command_line(pcm_file)
            
        except Exception as e:
            self.logger.error(f"PulseAudio播放失败: {e}")
            return False
    
    def _play_with_command_line(self, pcm_file: str) -> bool:
        """使用命令行工具播放PCM文件"""
        try:
            import subprocess
            
            # 尝试使用aplay播放
            aplay_cmd = [
                'aplay', '-t', 'raw', '-f', 'S16_LE', '-r', '16000', '-c', '1', pcm_file
            ]
            
            try:
                result = subprocess.run(aplay_cmd, check=True, capture_output=True, text=True, timeout=10)
                self.logger.info(f"aplay播放成功")
                return True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
                self.logger.warning(f"aplay播放失败: {e}")
            
            # 如果aplay失败，尝试使用ffplay（如果可用）
            ffplay_cmd = [
                'ffplay', '-nodisp', '-autoexit', '-f', 's16le', '-ar', '16000', '-ac', '1', pcm_file
            ]
            
            try:
                result = subprocess.run(ffplay_cmd, check=True, capture_output=True, text=True, timeout=10)
                self.logger.info(f"ffplay播放成功")
                return True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError) as e:
                self.logger.warning(f"ffplay播放失败: {e}")
            
            return False
            
        except Exception as e:
            self.logger.error(f"命令行播放失败: {e}")
            return False
    
    def _resample_audio(self, audio_data: np.ndarray, original_rate: int, target_rate: int) -> np.ndarray:
        """重采样音频数据"""
        try:
            # 使用简单的线性插值重采样
            original_length = len(audio_data)
            target_length = int(original_length * target_rate / original_rate)
            
            # 创建新的时间索引
            original_indices = np.linspace(0, original_length - 1, original_length)
            target_indices = np.linspace(0, original_length - 1, target_length)
            
            # 使用线性插值
            resampled_audio = np.interp(target_indices, original_indices, audio_data)
            
            self.logger.info(f"重采样: {original_rate}Hz -> {target_rate}Hz, 长度: {original_length} -> {target_length}")
            return resampled_audio
            
        except Exception as e:
            self.logger.error(f"重采样失败: {e}")
            return audio_data


class LocalSpeechSystem:
    """
    本地语音合成系统
    支持队列化的TTS合成和顺序播放
    """
    
    def __init__(self, speech_config: Optional[ConfigSpeechConfig] = None):
        self.speech_config = speech_config
        self.logger = logging.getLogger(__name__)
        
        # 语音队列和处理状态
        self.speech_queue = asyncio.Queue()
        self.is_processing = False
        self.queue_task = None
        
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
        self.audio_player = LocalAudioPlayer()
        
        # 确保输出目录存在
        output_dir = 'intelligence'
        os.makedirs(output_dir, exist_ok=True)
        self.output_dir = output_dir
        
        # 启动队列处理任务
        self._start_queue_processor()
    
    def _start_queue_processor(self):
        """启动队列处理任务，仅在有事件循环时启动"""
        if self.queue_task is None or self.queue_task.done():
            try:
                loop = asyncio.get_running_loop()
                if loop.is_running():
                    self.queue_task = asyncio.create_task(self._process_speech_queue())
                    self.logger.info("语音队列处理器已启动")
            except RuntimeError:
                self.logger.warning("没有正在运行的事件循环，语音队列处理器未启动。")
                self.queue_task = None
    
    async def _process_speech_queue(self):
        """处理语音队列中的所有任务"""
        self.logger.info("语音队列处理器启动")
        
        while True:
            try:
                # 等待队列中的任务
                speech_item = await self.speech_queue.get()
                
                if speech_item is None:  # 停止信号
                    self.logger.info("队列处理器收到停止信号")
                    break
                
                text, play_locally, result_future = speech_item
                
                try:
                    # 执行实际的语音合成和播放
                    result = await self._synthesize_and_play(text, play_locally)
                    
                    # 设置结果
                    if not result_future.done():
                        result_future.set_result(result)
                    
                except Exception as e:
                    self.logger.error(f"队列处理错误: {e}")
                    if not result_future.done():
                        result_future.set_result({
                            "success": False,
                            "message": f"队列处理错误: {e}"
                        })
                
                finally:
                    # 标记任务完成
                    self.speech_queue.task_done()
                    
            except asyncio.CancelledError:
                self.logger.info("队列处理器被取消")
                break
            except Exception as e:
                self.logger.error(f"队列处理器意外错误: {e}")
    
    async def say(self, text: str, play_locally: bool = True) -> Dict[str, Any]:
        """
        异步语音合成和本地播放 - 使用队列确保顺序处理
        
        Args:
            text: 要合成的文本
            play_locally: 是否在本地播放
            
        Returns:
            Dict: 操作结果
        """
        if not text.strip():
            return {"success": False, "message": "文本为空"}
        
        # 创建Future对象来接收结果
        result_future = asyncio.Future()
        
        # 将任务添加到队列中
        await self.speech_queue.put((text, play_locally, result_future))
        
        # 等待队列处理完成
        try:
            result = await result_future
            return result
        except Exception as e:
            self.logger.error(f"等待队列处理结果时发生错误: {e}")
            return {"success": False, "message": f"队列处理错误: {str(e)}"}
    
    async def _synthesize_and_play(self, text: str, play_locally: bool = True) -> Dict[str, Any]:
        """
        执行实际的语音合成和播放操作
        
        Args:
            text: 要合成的文本
            play_locally: 是否在本地播放
            
        Returns:
            Dict: 操作结果
        """
        try:
            # 生成唯一的文件名
            timestamp = int(time.time() * 1000)
            pcm_file = os.path.join(self.output_dir, f"tts_{timestamp}.pcm")
            
            self.logger.info(f"开始语音合成: {text}")
            
            # 异步语音合成
            success = await self.tts_engine.synthesize_speech(text, pcm_file)
            
            if not success:
                self.logger.error("语音合成失败")
                return {"success": False, "message": "语音合成失败"}
            
            # 本地播放音频
            if play_locally:
                self.logger.info("开始本地播放音频")
                play_success = await self._play_audio_locally(pcm_file)
                if not play_success:
                    self.logger.warning("本地音频播放失败，但合成成功")
            
            # 清理临时文件
            self._cleanup_files([pcm_file])
            
            self.logger.info(f"语音处理完成: {text}")
            return {
                "success": True,
                "message": "语音合成和播放完成",
                "text": text
            }
            
        except Exception as e:
            self.logger.error(f"语音合成系统错误: {e}")
            return {"success": False, "message": f"系统错误: {str(e)}"}
    
    async def _play_audio_locally(self, pcm_file: str) -> bool:
        """本地播放音频"""
        try:
            # 直接调用同步方法
            return self.audio_player.play_pcm_file_sync(pcm_file)
        except Exception as e:
            self.logger.error(f"本地音频播放错误: {e}")
            return False
    
    def _cleanup_files(self, files: list):
        """清理临时文件"""
        for file_path in files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except Exception as e:
                self.logger.warning(f"清理文件失败 {file_path}: {e}")
    
    async def test_speech(self, test_text: str = "本地语音合成系统测试正常") -> Dict[str, Any]:
        """测试语音合成系统"""
        self.logger.info("开始本地语音系统测试")
        result = await self.say(test_text)
        self.logger.info(f"本地语音系统测试结果: {result}")
        return result
    
    async def stop_speech_system(self):
        """停止语音系统"""
        self.logger.info("停止本地语音系统...")
        
        # 停止队列处理器
        if self.queue_task and not self.queue_task.done():
            # 发送停止信号
            await self.speech_queue.put(None)
            
            try:
                # 等待队列处理器结束
                await asyncio.wait_for(self.queue_task, timeout=5.0)
                self.logger.info("队列处理器已停止")
            except asyncio.TimeoutError:
                self.logger.warning("队列处理器停止超时，强制取消")
                self.queue_task.cancel()
        
        if hasattr(self, 'executor'):
            self.executor.shutdown(wait=False)
    
    def __del__(self):
        """清理资源"""
        try:
            # 同步清理资源
            if hasattr(self, 'executor'):
                self.executor.shutdown(wait=False)
            
            # 取消队列任务
            if hasattr(self, 'queue_task') and self.queue_task and not self.queue_task.done():
                self.queue_task.cancel()
        except:
            pass


# 测试功能
async def test_local_speech_system(speech_config: Optional[ConfigSpeechConfig] = None):
    """测试本地语音系统"""
    print("🎤 测试本地语音合成系统...")
    
    # 使用配置创建语音系统
    speech_system = LocalSpeechSystem(speech_config)
    
    # 测试基本功能
    test_texts = [
        "本地语音合成系统测试正常",
        "欢迎使用智慧零售机器人助手",
        "语音播放功能工作正常"
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
        
        # 等待一下再继续
        await asyncio.sleep(0.5)
    
    # 正确清理语音系统
    await speech_system.stop_speech_system()
    print("\n🎤 本地语音系统测试完成")


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
        
        asyncio.run(test_local_speech_system(speech_config))
    else:
        print("本地智能语音合成系统")
        print("使用方法:")
        print("  python speech_local.py test     - 测试语音合成")
        print("  或在代码中导入LocalSpeechSystem类使用")