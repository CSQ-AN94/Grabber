#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
专用于测试音频接收端的脚本。
它模拟GeminiAgent中的音频输入部分，启动一个TCP服务器，并打印接收到的数据。
这与GeminiAgent中的MicrophoneThread的行为完全一致。
"""
import asyncio
import logging
import sys
import os
import argparse

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sensors.microphone_thread import MicrophoneThread

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s')

async def main(port: int):
    """
    Initializes and starts the MicrophoneThread server, then prints received audio chunks.
    """
    logging.info(f"Initializing MicrophoneThread server on port {port}")
    
    # This is the component used by GeminiAgent to get audio. It's a TCP server.
    mic_thread = MicrophoneThread(port=port)
    
    try:
        mic_thread.start()
        logging.info(f"✅ MicrophoneThread server started. Waiting for a client to connect on port {port} and send audio...")
        
        chunk_count = 0
        while True:
            # We use the async method, just like GeminiAgent's _audio_input_loop
            chunk = await mic_thread.get_audio_chunk()
            if chunk:
                chunk_count += 1
                # Only log every 5th chunk to avoid spamming the console
                if chunk_count % 5 == 0:
                    logging.info(f"✅ Receiving audio stream... (Received chunk #{chunk_count}, Size: {len(chunk)} bytes)")
            else:
                # This is expected when no audio is being sent or between chunks
                await asyncio.sleep(0.1)

            # Print stats periodically
            if chunk_count > 0 and chunk_count % 100 == 0:
                stats = mic_thread.get_stats()
                logging.info(f"STATS: {stats}")

    except KeyboardInterrupt:
        logging.info("Keyboard interrupt received. Shutting down.")
    except Exception as e:
        logging.error(f"An error occurred: {e}", exc_info=True)
    finally:
        logging.info("Stopping MicrophoneThread server.")
        mic_thread.stop()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test MicrophoneThread Audio Receiver")
    # The default port in GeminiAgent is 8888
    parser.add_argument("--port", type=int, default=8888, help="The port for the audio server to listen on.")
    args = parser.parse_args()
    
    asyncio.run(main(args.port))
