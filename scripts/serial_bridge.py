#!/usr/bin/env python3
"""
Serial Bridge - TCP/IP bridge for USB Zigbee dongle
Allows Docker on Windows to access USB dongle through TCP
"""

import serial
import socket
import threading
import time
import sys

# Configuration
SERIAL_PORT = "COM3"  # Change according to your COM port
SERIAL_BAUDRATE = 115200
TCP_HOST = "0.0.0.0"
TCP_PORT = 8282

class SerialBridge:
    def __init__(self):
        self.serial_port = None
        self.server_socket = None
        self.client_socket = None
        self.running = False
        
    def connect_serial(self):
        """Connect to serial port"""
        try:
            self.serial_port = serial.Serial(
                port=SERIAL_PORT,
                baudrate=SERIAL_BAUDRATE,
                timeout=1,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False
            )
            print(f"✓ Connected to {SERIAL_PORT} @ {SERIAL_BAUDRATE} baud")
            return True
        except Exception as e:
            print(f"✗ Error connecting to {SERIAL_PORT}: {e}")
            return False
    
    def start_server(self):
        """Start TCP server"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((TCP_HOST, TCP_PORT))
            self.server_socket.listen(1)
            print(f"✓ TCP server started on {TCP_HOST}:{TCP_PORT}")
            return True
        except Exception as e:
            print(f"✗ Error starting TCP server: {e}")
            return False
    
    def serial_to_tcp(self):
        """Read from serial and send to TCP"""
        while self.running:
            try:
                if self.serial_port and self.serial_port.in_waiting > 0:
                    data = self.serial_port.read(self.serial_port.in_waiting)
                    if self.client_socket and data:
                        self.client_socket.sendall(data)
            except Exception as e:
                print(f"✗ Error serial->TCP: {e}")
                break
            time.sleep(0.001)
    
    def tcp_to_serial(self):
        """Read from TCP and send to serial"""
        while self.running:
            try:
                if self.client_socket:
                    data = self.client_socket.recv(4096)
                    if not data:
                        break
                    if self.serial_port:
                        self.serial_port.write(data)
            except Exception as e:
                print(f"✗ Error TCP->serial: {e}")
                break
            time.sleep(0.001)
    
    def run(self):
        """Run the bridge"""
        if not self.connect_serial():
            return
        
        if not self.start_server():
            return
        
        print("\n🔌 Serial Bridge active")
        print(f"   Serial: {SERIAL_PORT} @ {SERIAL_BAUDRATE}")
        print(f"   TCP: {TCP_HOST}:{TCP_PORT}")
        print("\n⏳ Waiting for Zigbee2MQTT connection...")
        
        while True:
            try:
                self.client_socket, addr = self.server_socket.accept()
                print(f"\n✓ Client connected from {addr}")
                
                self.running = True
                
                # Threads for bidirectional communication
                t1 = threading.Thread(target=self.serial_to_tcp, daemon=True)
                t2 = threading.Thread(target=self.tcp_to_serial, daemon=True)
                
                t1.start()
                t2.start()
                
                # Wait for threads to finish
                t1.join()
                t2.join()
                
                print("\n✗ Client disconnected")
                self.running = False
                self.client_socket.close()
                self.client_socket = None
                
                print("⏳ Waiting for new connection...")
                
            except KeyboardInterrupt:
                print("\n\n🛑 Stopping Serial Bridge...")
                break
            except Exception as e:
                print(f"\n✗ Error: {e}")
                time.sleep(1)
        
        # Cleanup
        if self.serial_port:
            self.serial_port.close()
        if self.server_socket:
            self.server_socket.close()
        
        print("✓ Serial Bridge stopped")

if __name__ == "__main__":
    # Show available COM ports
    print("🔍 Looking for available COM ports...")
    try:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
        if ports:
            print("\nDetected COM ports:")
            for port in ports:
                print(f"  - {port.device}: {port.description}")
        else:
            print("  No COM ports found")
    except:
        pass
    
    print(f"\n⚙️  Current configuration:")
    print(f"   COM Port: {SERIAL_PORT}")
    print(f"   Change in line 14 if needed\n")
    
    bridge = SerialBridge()
    bridge.run()
