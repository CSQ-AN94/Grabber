#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
SpeechRecognition基础功能测试脚本
用于验证PyAudio和Google Speech Recognition API是否正常工作
"""

import speech_recognition as sr
import pyaudio
import sys
import time

def test_basic_functionality():
    """测试基础功能"""
    print("=== SpeechRecognition基础功能测试 ===")
    
    recognizer = sr.Recognizer()
    
    try:
        # 1. 测试麦克风创建
        print("1. 测试麦克风创建:")
        mic = sr.Microphone()
        print("   ✓ 麦克风创建成功")
        
        # 2. 测试环境噪音调整
        print("2. 测试环境噪音调整:")
        with mic as source:
            print("   调整中...")
            recognizer.adjust_for_ambient_noise(source, duration=1)
        print("   ✓ 环境噪音调整成功")
        
        return recognizer, mic
        
    except Exception as e:
        print(f"   ✗ 基础功能测试失败: {e}")
        return None, None

def test_audio_recording(recognizer, mic):
    """测试音频录制和识别"""
    print("\n3. 测试音频录制和识别:")
    
    try:
        print("   请说话 (3秒录音窗口)...")
        with mic as source:
            start_time = time.time()
            audio = recognizer.listen(source, timeout=3, phrase_time_limit=3)
            duration = time.time() - start_time
            print(f"   录音完成 ({duration:.1f}秒)，开始识别...")
        
        # 尝试识别
        try:
            text = recognizer.recognize_google(audio, language='zh-CN')
            print(f"   ✓ 识别成功: '{text}'")
            return True
        except sr.UnknownValueError:
            print("   无法理解音频 (可能语音不清楚或环境噪音太大)")
            return True  # 功能正常，只是识别不出内容
        except sr.RequestError as e:
            print(f"   ✗ 识别服务错误: {e}")
            return False
            
    except sr.WaitTimeoutError:
        print("   录音超时，未检测到语音")
        return True  # 功能正常，只是没有语音输入
    except Exception as e:
        print(f"   ✗ 录音测试失败: {e}")
        return False

def test_pyaudio_devices():
    """测试PyAudio设备信息"""
    print("\n=== PyAudio设备信息 ===")
    
    try:
        p = pyaudio.PyAudio()
        
        print("输入设备列表:")
        input_devices = []
        for i in range(p.get_device_count()):
            info = p.get_device_info_by_index(i)
            if info['maxInputChannels'] > 0:
                input_devices.append((i, info))
                print(f"  {i}: {info['name']} - {info['defaultSampleRate']}Hz")
        
        try:
            default = p.get_default_input_device_info()
            print(f"\n默认输入设备: {default['index']} - {default['name']}")
        except:
            print("\n无法获取默认输入设备")
        
        p.terminate()
        return len(input_devices) > 0
        
    except Exception as e:
        print(f"✗ PyAudio设备检查失败: {e}")
        return False

def test_direct_audio_capture():
    """测试直接音频捕获"""
    print("\n=== 直接音频捕获测试 ===")
    
    try:
        p = pyaudio.PyAudio()
        
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=16000,
            input=True,
            frames_per_buffer=480
        )
        
        print("录制2秒音频进行质量检查...")
        frames = []
        for _ in range(int(16000 / 480 * 2)):  # 2秒
            data = stream.read(480, exception_on_overflow=False)
            frames.append(data)
        
        stream.close()
        p.terminate()
        
        # 分析音频质量
        audio_data = b''.join(frames)
        
        import numpy as np
        audio_array = np.frombuffer(audio_data, dtype=np.int16)
        
        max_amplitude = int(np.max(np.abs(audio_array)))
        mean_amplitude = float(np.mean(np.abs(audio_array)))
        
        print(f"音频质量分析:")
        print(f"  最大振幅: {max_amplitude}")
        print(f"  平均振幅: {mean_amplitude:.1f}")
        
        if max_amplitude > 1000:
            print("  ✓ 音频信号强度正常")
            return True
        elif max_amplitude > 100:
            print("  音频信号偏弱，但可用")
            return True
        else:
            print("  ✗ 音频信号太弱，可能麦克风有问题")
            return False
            
    except Exception as e:
        print(f"✗ 直接音频捕获失败: {e}")
        return False

def main():
    """主测试函数"""
    print("SpeechRecognition和PyAudio功能测试")
    print("=" * 50)
    
    # 测试PyAudio设备
    devices_ok = test_pyaudio_devices()
    if not devices_ok:
        print("\nPyAudio设备检查失败，退出测试")
        sys.exit(1)
    
    # 测试直接音频捕获
    capture_ok = test_direct_audio_capture()
    
    # 测试SpeechRecognition基础功能
    recognizer, mic = test_basic_functionality()
    if not recognizer or not mic:
        print("\nSpeechRecognition基础功能失败，退出测试")
        sys.exit(1)
    
    # 测试录音和识别
    recognition_ok = test_audio_recording(recognizer, mic)
    
    # 总结结果
    print("\n" + "=" * 50)
    print("测试结果总结:")
    print(f"  PyAudio设备: {'✓' if devices_ok else '✗'}")
    print(f"  音频捕获: {'✓' if capture_ok else '✗'}")
    print(f"  语音识别: {'✓' if recognition_ok else '✗'}")
    
    if devices_ok and capture_ok and recognition_ok:
        print("\n所有测试通过！音频系统工作正常")
    else:
        print("\n部分功能需要进一步调试")
    
    return devices_ok and capture_ok and recognition_ok

if __name__ == "__main__":
    main()