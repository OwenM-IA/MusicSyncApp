import asyncio

from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

LOCAL_IP = "127.0.0.1"
ABLETONOSC_SEND_PORT = 11000
ABLETONOSC_RECEIVE_PORT = 11001

currentSongBeat = 0.0


def beatCallback(address, *args):
    global currentSongBeat

    currentSongBeat = (float(args[0]) - 7) % 252.0

    print(f"Song Beat: {currentSongBeat:.3f}")


async def beatMonitorTask():
    while True:
        oscClient.send_message(
            "/live/song/get/current_song_time",
            []
        )

        await asyncio.sleep(0.05)


async def main():
    global oscClient

    oscClient = SimpleUDPClient(
        LOCAL_IP,
        ABLETONOSC_SEND_PORT
    )

    dispatcher = Dispatcher()

    dispatcher.map(
        "/live/song/get/current_song_time",
        beatCallback
    )

    server = ThreadingOSCUDPServer(
        (LOCAL_IP, ABLETONOSC_RECEIVE_PORT),
        dispatcher
    )

    asyncio.get_running_loop().run_in_executor(
        None,
        server.serve_forever
    )

    print(
        "Listening for Ableton OSC messages on port",
        ABLETONOSC_RECEIVE_PORT
    )

    await beatMonitorTask()


if __name__ == "__main__":
    asyncio.run(main())