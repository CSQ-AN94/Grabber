#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Notebook-side Speaker Server.

This script runs on the local Ubuntu notebook (outside of Docker).
It starts a TCP server that listens for incoming audio streams from the Jetson
(e.g., from the TTS system) and plays them through the notebook's speakers.
"""
import socket
import sounddevice as sd
import numpy as np
import threading
import logging
import argparse
from queue import Queue, Empty, Full

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SpeakerServer:
    def __init__(self, host: str, port: int, sample_rate: int = 16000, channels: int = 1):
        self.host = host
        self.port = port
        self.sample_rate = sample_rate
        self.channels = channels
        self.dtype = np.int16
        self.chunk_size = 1024  # Standard chunk size

        self.server_socket = None
        self.client_socket = None
        self.is_running = False
        
        self.audio_queue = Queue(maxsize=100)
        self.output_stream = None
        self.server_thread = None

    def _audio_output_callback(self, outdata, frames, time, status):
        """Callback for the sounddevice output stream."""
        if status:
            logging.warning(f"Audio output status warning: {status}")
        try:
            # Get a chunk of audio data from the queue
            audio_chunk = self.audio_queue.get_nowait()
            
            # Convert bytes to numpy array
            audio_data = np.frombuffer(audio_chunk, dtype=self.dtype)
            
            # Reshape for sounddevice
            outdata[:] = audio_data.reshape(-1, self.channels)
            
        except Empty:
            # Queue is empty, play silence
            outdata.fill(0)
        except Exception as e:
            logging.error(f"Error in audio callback: {e}")
            outdata.fill(0)

    def _handle_client(self, client_socket: socket.socket):
        """Handle an incoming client connection."""
        self.client_socket = client_socket
        logging.info(f"Audio source connected from: {client_socket.getpeername()}")
        
        while self.is_running and self.client_socket:
            try:
                # Receive audio data from Jetson
                data = self.client_socket.recv(self.chunk_size * 2) # Read one chunk at a time
                if not data:
                    logging.info("Client disconnected.")
                    break
                
                # Put data into the queue for playback
                try:
                    self.audio_queue.put_nowait(data)
                except Full:
                    # If queue is full, drop the oldest chunk to reduce latency
                    self.audio_queue.get_nowait()
                    self.audio_queue.put_nowait(data)

            except ConnectionResetError:
                logging.warning("Client connection reset.")
                break
            except Exception as e:
                logging.error(f"Error receiving data: {e}")
                break
        
        if self.client_socket:
            self.client_socket.close()
            self.client_socket = None
        logging.info("Client connection closed.")

    def _server_loop(self):
        """The main loop for the TCP server."""
        self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.server_socket.bind((self.host, self.port))
        self.server_socket.listen(1)
        logging.info(f"✅ Speaker server listening on {self.host}:{self.port}")

        while self.is_running:
            try:
                client, _ = self.server_socket.accept()
                self._handle_client(client)
            except OSError:
                # This can happen when the socket is closed while accept() is blocking
                break
            except Exception as e:
                if self.is_running:
                    logging.error(f"Server loop error: {e}")

    def start(self):
        """Start the speaker server and the audio output stream."""
        if self.is_running:
            return
            
        self.is_running = True
        
        # Start the audio output stream
        self.output_stream = sd.OutputStream(
            samplerate=self.sample_rate,
            blocksize=self.chunk_size,
            channels=self.channels,
            dtype=self.dtype,
            callback=self._audio_output_callback
        )
        self.output_stream.start()
        logging.info("Audio output stream started.")
        
        # Start the TCP server in a separate thread
        self.server_thread = threading.Thread(target=self._server_loop, daemon=True)
        self.server_thread.start()

    def stop(self):
        """Stop the server and clean up resources."""
        self.is_running = False
        
        if self.server_socket:
            self.server_socket.close()
            self.server_socket = None
            
        if self.server_thread and self.server_thread.is_alive():
            self.server_thread.join(timeout=1)
            
        if self.output_stream:
            self.output_stream.stop()
            self.output_stream.close()
            logging.info("Audio output stream stopped.")
            
        logging.info("Speaker server stopped.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Notebook Speaker Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to listen on (0.0.0.0 for all interfaces).")
    parser.add_argument("--port", type=int, default=9889, help="Port to listen on for incoming audio.")
    args = parser.parse_args()

    server = SpeakerServer(host=args.host, port=args.port)
    try:
        server.start()
        # Keep the main thread alive
        while True:
            threading.Event().wait(1)
    except KeyboardInterrupt:
        logging.info("Shutting down...")
    finally:
        server.stop()
