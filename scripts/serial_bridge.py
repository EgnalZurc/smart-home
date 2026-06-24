#!/usr/bin/env python3
"""
Serial Bridge - Puente TCP/IP para dongle Zigbee USB
Permite que Docker en Windows acceda al dongle USB a través de TCP
"""

import serial
import socket
import threading
import time
import sys

# Configuración
SERIAL_PORT = "COM3"  # Cambiar según tu puerto COM
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
        """Conecta al puerto serial"""
        try:
            self.serial_port = serial.Serial(
                port=SERIAL_PORT,
                baudrate=SERIAL_BAUDRATE,
                timeout=1,
                xonxoff=False,
                rtscts=False,
                dsrdtr=False
            )
            print(f"✓ Conectado a {SERIAL_PORT} @ {SERIAL_BAUDRATE} baud")
            return True
        except Exception as e:
            print(f"✗ Error conectando a {SERIAL_PORT}: {e}")
            return False
    
    def start_server(self):
        """Inicia el servidor TCP"""
        try:
            self.server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.server_socket.bind((TCP_HOST, TCP_PORT))
            self.server_socket.listen(1)
            print(f"✓ Servidor TCP iniciado en {TCP_HOST}:{TCP_PORT}")
            return True
        except Exception as e:
            print(f"✗ Error iniciando servidor TCP: {e}")
            return False
    
    def serial_to_tcp(self):
        """Lee del serial y envía a TCP"""
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
        """Lee de TCP y envía al serial"""
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
        """Ejecuta el bridge"""
        if not self.connect_serial():
            return
        
        if not self.start_server():
            return
        
        print("\n🔌 Serial Bridge activo")
        print(f"   Serial: {SERIAL_PORT} @ {SERIAL_BAUDRATE}")
        print(f"   TCP: {TCP_HOST}:{TCP_PORT}")
        print("\n⏳ Esperando conexión de Zigbee2MQTT...")
        
        while True:
            try:
                self.client_socket, addr = self.server_socket.accept()
                print(f"\n✓ Cliente conectado desde {addr}")
                
                self.running = True
                
                # Threads para bidireccional
                t1 = threading.Thread(target=self.serial_to_tcp, daemon=True)
                t2 = threading.Thread(target=self.tcp_to_serial, daemon=True)
                
                t1.start()
                t2.start()
                
                # Esperar a que terminen
                t1.join()
                t2.join()
                
                print("\n✗ Cliente desconectado")
                self.running = False
                self.client_socket.close()
                self.client_socket = None
                
                print("⏳ Esperando nueva conexión...")
                
            except KeyboardInterrupt:
                print("\n\n🛑 Deteniendo Serial Bridge...")
                break
            except Exception as e:
                print(f"\n✗ Error: {e}")
                time.sleep(1)
        
        # Cleanup
        if self.serial_port:
            self.serial_port.close()
        if self.server_socket:
            self.server_socket.close()
        
        print("✓ Serial Bridge detenido")

if __name__ == "__main__":
    # Mostrar puertos COM disponibles
    print("🔍 Buscando puertos COM disponibles...")
    try:
        from serial.tools import list_ports
        ports = list(list_ports.comports())
        if ports:
            print("\nPuertos COM detectados:")
            for port in ports:
                print(f"  - {port.device}: {port.description}")
        else:
            print("  No se encontraron puertos COM")
    except:
        pass
    
    print(f"\n⚙️  Configuración actual:")
    print(f"   Puerto COM: {SERIAL_PORT}")
    print(f"   Cambiar en línea 11 si es necesario\n")
    
    bridge = SerialBridge()
    bridge.run()
