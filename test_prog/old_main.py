# Symphoni Music Syncronization Application
# Owen Marshall, 15-Sep-2026

import threading
import time

from pycomm3 import LogixDriver
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

Running = True
POLLING_INTERVAL = 0.1 # In seconds
PLC_IP = "192.168.1.2"
LOCAL_IP = "127.0.0.1"
ABLETONOSC_SEND_PORT = 11000
ABLETONOSC_RECIEVE_PORT = 11001
MIN_OFFSET_BPM = -30
MAX_OFFSET_BPM = 80

SONGS = {
    0: {"name": "Drum Beat", "base_bpm": 60},
    1: {"name": "Fur Elise",       "base_bpm": 120},
    2: {"name": "We Will Rock You",        "base_bpm": 81},
    3: {"name": "Flight of the bumblebee",       "base_bpm": 120},
}

def tempoCallback(address, *args):
    print("Received from Ableton: ", address, " ", args)

def plcTask(plc, client):

    lastTempo = None
    lastSong = None
    scene = 0

    while Running:
        # Song Read
        song = plc.read("_gOBit").value
        for bit in range(5): # Bitwise read in to the program, get scene number from _gOBit
            if song & (1 << bit):
                scene = bit
                break

        # Tempo Read
        slider = plc.read("_gNiBIT").value # 0-100

        # Calculate tempo based on song
        baseBpm = SONGS[scene]["base_bpm"]
        offset = MIN_OFFSET_BPM + ((MAX_OFFSET_BPM - MIN_OFFSET_BPM) * slider / 100)
        tempo = baseBpm + offset

        if song != lastSong:
            client.send_message("/live/scene/fire", scene)
            print(f"Scene {scene} launched")
            lastSong = song

        if tempo != lastTempo:
            client.send_message("/live/song/set/tempo", tempo)
            print(f"Tempo set to {tempo} BPM")
            lastTempo = tempo

        time.sleep(POLLING_INTERVAL)

# Main
def main():
    global Running
    
    # Open PLC socket
    try:
        plc = LogixDriver(PLC_IP)
        plc.open()
        print("PLC connection opened")
    except Exception as e:  # noqa: BLE001
        print("Error in opening PLC connection: ", e)

    # Open AbletonOSC Connection
    try:
        client = SimpleUDPClient(LOCAL_IP, ABLETONOSC_SEND_PORT)
        dispatcher = Dispatcher()

        dispatcher.map(
            "/live/song/get/tempo",
            tempoCallback
        )

        server = ThreadingOSCUDPServer(
            (LOCAL_IP, ABLETONOSC_RECIEVE_PORT),
            dispatcher
        )

        threading.Thread(
            target=server.serve_forever,
            daemon=True
        ).start()

        print("Listening for Ableton OSC messages on port: ", ABLETONOSC_RECIEVE_PORT)
    except Exception as e:  # noqa: BLE001
        print("Error in setting up UDP connection to abletonOSC: ", e)

    # Run
    try:
        # Start PLC Task
        plcThread = threading.Thread(
            target=plcTask,
            args=(plc, client),
            daemon=True
        )
        plcThread.start()

        while Running:
            time.sleep(1)

    except KeyboardInterrupt:
        print("Task stopped by user")  

    finally:
        # Close PLC connection
        client.send_message("/live/song/stop_all_clips", [])
        Running = False

        server.shutdown()
        server.server_close()

        plcThread.join()
        plc.close()    

if __name__ == "__main__":
    main()
