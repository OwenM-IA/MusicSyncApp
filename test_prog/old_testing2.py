import threading
import time

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient


def clip_callback(address, *args):
    #print("Received:", address, args)
    return
oscClient = SimpleUDPClient("127.0.0.1", 11000)
#osc.send_message("/live/clip/set/warping", [0, 0, 1]) # Turn warping on
#osc.send_message("/live/clip/set/warp_mode", [0, 0, 6]) # Complex pro warping
#oscClient.send_message("/live/song/stop_all_clips", [])
#oscClient.send_message("/live/song/stop_playing", [])
"""
dispatcher = Dispatcher()
dispatcher.map("/live/clip/get/playing_position", clip_callback)

server = ThreadingOSCUDPServer(("127.0.0.1", 11001), dispatcher)
threading.Thread(target=server.serve_forever, daemon=True).start()

# Listen to clip position
osc.send_message("/live/clip/start_listen/playing_position", [0, 0])

print("Waiting 5 seconds...")
time.sleep(5)
"""
oscClient.send_message("/live/track/set/volume", [0, 1])
time.sleep(5)
#oscClient.send_message("/live/clip/set/ram_mode", [0, 1, 1])
#oscClient.send_message("/live/track/set/volume", [0, 0.5])
print("Attempting to set clip position to 0")
#oscClient.send_message("/live/scene/fire",0)
time.sleep(5)

#oscClient.send_message("/live/song/set/current_song_time",float(15))
print("Done")

#while True:
#    time.sleep(1)