# Symphoni Music Synchronization Application
# Owen Marshall, 15-Sep-2026
"""
This program is designed to faciliate and align communication between the PLC and Ableton.

Libraries to install (can be done with pip install <lib-name>):
 - asycuna
 - python_osc

To do this it uses AbletonOSC for the python<->ableton connection and asyncua (library built ontop of python-opcua) for PLC<->python (comms through opcUA*)
*OPCUA was added in RSLogix V36

This program works fundamentally by converting a master servo speed (controls the speed of the whole machine) into a BPM to assign a tempo to a song
and using gCell_BeatCount (a beatcount calculated in the PLC that covers a full cycle of the machine) to know when the beats in the song are supposed 
to occur. Small adjustments are made based on that to line up the song.
"""

import asyncio
import json
import logging
import sys
import time
import traceback

from asyncua import Client as OpcUaClient
from asyncua import ua
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

# Logging init:
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s.%(msecs)03d [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.FileHandler("console.log"),
        logging.StreamHandler()
    ]
)

log = logging.getLogger("Symphoni")
logging.getLogger("asyncua").setLevel(logging.WARNING)
logging.getLogger("asyncio").setLevel(logging.WARNING)

def log_uncaught_exception(exc_type, exc_value, exc_traceback):
    log.error(
        "".join(
            traceback.format_exception(
                exc_type,
                exc_value,
                exc_traceback
            )
        )
    )

sys.excepthook = log_uncaught_exception

# First load the config file
try:
    with open("config.json", "r") as f:
        CONFIG = json.load(f)

except Exception as e:
    log.error(f"Failed to load config.json: {e}")

    with open("console.log", "a") as log:
        log.write(f"ERROR: Failed to load config.json: {e}\n")

    input("Press Enter to exit...")
    sys.exit(1)

# Configurable constants
LOW_TEMPO_THRESHOLD = CONFIG["tempo"]["minimumTempo"] # Min tempo ableton allows
LOW_TEMPO_DELAY = CONFIG["tempo"]["muteDelay"] # Seconds till low tempo turns off music

# Sync
BEAT_INTERVAL_SCALING_FACTOR = CONFIG["sync"]["beatScalingFactor"] # Beat Inverval Scaling Factor (14 actions (pick/place) in one small cycle)
NUDGE_ACTIVATION_THRESHOLD = CONFIG["sync"]["nudgeThreshold"] # Threshold to activate nudging in beat difference
SNAP_ACTIVATION_THRESHOLD = CONFIG["sync"]["snapThreshold"]
IGNORE_SYNC_DELAY = CONFIG["sync"]["ignoreSyncTime"] # Delay before checking if the sync worked

# Audio
TRACK_INDEX = CONFIG["audio"]["trackIndex"]
TOTAL_BEAT_COUNT = CONFIG["sync"]["totalBeatCount"]
TOTAL_SONG_COUNT = CONFIG["audio"]["totalSongCount"]
DEFAULT_WARPING_MODE = CONFIG["audio"]["defaultWarpingMode"]

# OPC UA
OPCUA_ENDPOINT = CONFIG["opcua"]["endpoint"]

TEMPO_NODE_ID = CONFIG["nodes"]["tempo"]
BEAT_COUNT_ID = CONFIG["nodes"]["beatCount"]
SONG_SELECT_NODE_ID = CONFIG["nodes"]["songSelection"]
VOLUME_NODE_ID = CONFIG["nodes"]["volume"]
MUSIC_ENABLE_NODE_ID = CONFIG["nodes"]["musicEnable"]
CHIPMUNK_ENABLE_NODE_ID = CONFIG["nodes"]["chipmunkEnable"]
HEARTBEAT_NODE_ID = CONFIG["nodes"]["heartbeat"]

# Ableton
LOCAL_IP = CONFIG["ableton"]["ip"]
ABLETONOSC_SEND_PORT = CONFIG["ableton"]["sendPort"]
ABLETONOSC_RECEIVE_PORT = CONFIG["ableton"]["receivePort"]

# Offset (don't touch this has been tuned)
BEAT_OFFSET = CONFIG["sync"]["beatOffset"]

# Globals
lowTempoStartTime = None
musicMutedForLowTempo = False

ignoreSyncUntil = 0

Running = True
phaseCorrectionRunning = False
sceneLaunchRunning = False
lastTempo = None
songSelection = 0
lastSong = None
musicEnabled = 0
chipmunkEnabled = 0
# Based on the tempo allow more or less time for certain actions such as nudges
applicationSpeedScaling = 1 # 0.8->3

# Counts
currentAbletonBeat = 0.0
currentClipPosition = 0.0
currentPLCBeat = 0
previousPLCBeat = 0
PLCMasterSpeed = 0.0
beatSnapCounter = 0

# OPC UA
oscClient = None

# Get the current tempo from ableton
def tempoCallback(address, *args):
    log.info(f"Received from Ableton: {address}, {args}")

# Get the current tempo from ableton
def clipPositionCallback(address, *args):
    global currentClipPosition
    currentClipPosition = float(args[2]) # (track, clip, position)

# Helper function for heartbeat task (as writing bool takes work)
async def writeBool(node, value):
    dv = ua.DataValue()
    dv.Value = ua.Variant(value, ua.VariantType.Boolean)
    await node.write_attribute(ua.AttributeIds.Value, dv)

# Heartbeat to send to the PLC so it knows the prog is still active
async def heartbeatTask(heartbeatNode):
    heartbeat = False

    while Running:
        heartbeat = not heartbeat

        await writeBool(heartbeatNode, heartbeat)
        await asyncio.sleep(0.5)

# Calculate the tempo to send to Ableton from the master servo speed on the PLC
def calculateTempo():
    return round(PLCMasterSpeed * BEAT_INTERVAL_SCALING_FACTOR, 2)

# This is used to Nudge (shortly increase/decrease the tempo) or jump (set) the spot in the baes on the PLC beat or do nothing
# This decision is based on the error calculated between the PLC's beat and Ableton's beat
async def phaseCorrect(error, scene):
    global phaseCorrectionRunning
    global ignoreSyncUntil
    global beatSnapCounter

    if time.time() < ignoreSyncUntil: # If jump sync is already active wait until Ableton actually completes the jump
        return
    if phaseCorrectionRunning or sceneLaunchRunning:
        return
    phaseCorrectionRunning = True

    try:
        if abs(error) < (NUDGE_ACTIVATION_THRESHOLD * (1/applicationSpeedScaling)): # Small error, do nothing
            oscClient.send_message("/live/song/set/nudge_up",0)
            oscClient.send_message("/live/song/set/nudge_down",0)
            beatSnapCounter = 0

            return

        if abs(error) > (SNAP_ACTIVATION_THRESHOLD * (1/applicationSpeedScaling)): # Big difference, jump the spot of the song to currentPLCBeat
            if beatSnapCounter > 2: # Occasionally the prog gets stuck continuously snapping but no feedback is seen on ableton
                log.error("Desynced clip position and arrangement position, resetting song")
                oscClient.send_message("/live/song/stop_playing", [])
                oscClient.send_message("/live/song/stop_all_clips", [])
                await asyncio.sleep(0.05)
                oscClient.send_message("/live/clip/start_listen/playing_position", [0, songSelection]) # Update clip listener to song
                oscClient.send_message("/live/song/set/current_song_time", 0)
                await asyncio.sleep(1)
                asyncio.create_task(launchScene(songSelection, calculateTempo(), 1))
                await asyncio.sleep(0.05)
                log.error(f"Finished attempt to reset song {songSelection}")

                beatSnapCounter = 0
                return

            oscClient.send_message("/live/song/set/current_song_time",float(currentPLCBeat))
            if abs(error) > 3:
                beatSnapCounter += 1
                log.warning(f"Beat Snap on large error occured. Counter: {beatSnapCounter}")

            ignoreSyncUntil = time.time() + IGNORE_SYNC_DELAY # Allow time for ableton to update

            log.warning(f"Snapping to beat {currentPLCBeat}")

            oscClient.send_message("/live/song/set/nudge_up", 0)
            oscClient.send_message("/live/song/set/nudge_down", 0)

            return
        
        beatSnapCounter = 0
        if error > 0: # Song is slightly ahead
            log.warning("Nudge Down")
            oscClient.send_message("/live/song/set/nudge_down", 1)
            await asyncio.sleep(min(abs(error)*2.5*(applicationSpeedScaling*2), 1))

        else: # Song is slightly behind
            log.warning("Nudge Up")
            oscClient.send_message("/live/song/set/nudge_up", 1)
            await asyncio.sleep(min(abs(error)*2.5*(applicationSpeedScaling*2), 1))

        # Turn nudge off
        oscClient.send_message("/live/song/set/nudge_up", 0)
        oscClient.send_message("/live/song/set/nudge_down", 0)

    finally:
        phaseCorrectionRunning = False

# Starup the scene specified at specified tempo; also set the current song time to the PLC's current beat
# Additional delay param added for retries on faulty song launches to allow ableton time to sort itself out
async def launchScene(scene, tempo, additionalSetTimeDelay):
    global sceneLaunchRunning
    if sceneLaunchRunning:
        log.warning(f"Launch blocked for scene {scene}")
        return
    sceneLaunchRunning = True
    try: 
        oscClient.send_message("/live/song/set/tempo",tempo)
        oscClient.send_message("/live/scene/fire",scene)
        oscClient.send_message("/live/track/set/mute", [0, 1])
        log.info("Delay to allow for song startup [started]")
        await asyncio.sleep(1 + additionalSetTimeDelay)
        log.info("Delay to allow for song startup [finished]")
        if musicEnabled:
            oscClient.send_message("/live/track/set/mute", [0, 0])
        oscClient.send_message("/live/song/set/current_song_time", float(currentPLCBeat+0.5))          
    finally:                     
        log.info(f"Scene {scene} launched, Tempo set to {tempo} BPM")
        sceneLaunchRunning = False

# SubscriptionHandler class holds datachange_notification which is used to watch for changes on the nodes setup in opcTask
# datachange_notification is called when any of the endpoints change, logic is used to determine which one
# Based on the node that is updated specific logic is run
class SubscriptionHandler:
    def datachange_notification(self, node, value, data):
        global PLCMasterSpeed     
        global currentPLCBeat
        global previousPLCBeat

        global musicEnabled
        global chipmunkEnabled
        
        global songSelection
        global lastSong           
        global lastTempo
        global lowTempoStartTime
        global musicMutedForLowTempo

        global applicationSpeedScaling

        try:
            nodeId = node.nodeid.to_string() # Get node that has had datachange

            # Tempo change, if the tempo is new update it
            if nodeId == TEMPO_NODE_ID: 
                PLCMasterSpeed = value
                tempo = calculateTempo()
                
                if lastTempo is None:
                    lastTempo = tempo
                    return
                
                if tempo != lastTempo:
                    global lowTempoStartTime
                    if tempo < LOW_TEMPO_THRESHOLD:
                        if lowTempoStartTime is None:
                            lowTempoStartTime = time.time()

                    else:
                        lowTempoStartTime = None

                        if musicMutedForLowTempo:
                            log.info("Unmuting Music - Tempo Recovered")
                            oscClient.send_message("/live/song/set/current_song_time", float(currentPLCBeat))
                            #oscClient.send_message("/live/scene/fire",0)                            

                            if musicEnabled:
                                oscClient.send_message("/live/track/set/mute", [0, 0])

                            musicMutedForLowTempo = False

                        if abs(tempo - lastTempo) > 0.25:
                            oscClient.send_message("/live/song/set/tempo", tempo)
                            log.info(f"Tempo set to {tempo} BPM")
                            if tempo != 0:
                                applicationSpeedScaling = 1/(tempo/120)

                    lastTempo = tempo

            # Beat count change, use offset (-8) to lineup PLC beat with cycle that makes sense for running a song
            # Handles signal bouncing in beat value from PLC; also calculates song beat error between PLC and Ableton
            elif nodeId == BEAT_COUNT_ID:
                currentPLCBeat = (float(value) - BEAT_OFFSET) % TOTAL_BEAT_COUNT # Minus 8, the loop of the machine starts not at 0 (0 meaning 0 from the PLC)

                # Guard from beat count bounce from PLC
                delta = abs(previousPLCBeat-currentPLCBeat)
                if delta == 14 or delta == 238 or currentPLCBeat == previousPLCBeat:
                    log.warning(f"Rejected beat count bounce {previousPLCBeat}->{currentPLCBeat}")
                    return
                
                # Beat count logic
                clipBeatMod = currentClipPosition % TOTAL_BEAT_COUNT
                error = ((clipBeatMod - currentPLCBeat + (TOTAL_BEAT_COUNT/2)) % TOTAL_BEAT_COUNT) - (TOTAL_BEAT_COUNT/2)
                
                if currentPLCBeat == 0: # Everytime when resetting 
                    log.info("Syncing track...")
                    oscClient.send_message("/live/song/set/current_song_time", 0)

                log.info(f"\t\t\t\t\t\t\tMachine={currentPLCBeat:.0f} Song={clipBeatMod:.3f} Phase Error={error:.3f}")
                asyncio.create_task(phaseCorrect(error, 0))
                previousPLCBeat = currentPLCBeat

            # Music enable from the PLC, mute music if 0
            elif nodeId == MUSIC_ENABLE_NODE_ID:
                musicEnabled = value
                if musicEnabled:
                    log.info("Un-Muting Music")
                    oscClient.send_message("/live/track/set/mute", [0, 0]) # unmute
                else:
                    log.info("Muting Music")
                    oscClient.send_message("/live/track/set/mute", [0, 1]) # mute

            # Turn on pitch warp mode (pitch scaling)
            elif nodeId == CHIPMUNK_ENABLE_NODE_ID:
                chipmunkEnabled = value
                if chipmunkEnabled:
                    log.info("Chipmunk ON")
                    for i in range(TOTAL_SONG_COUNT+1):
                        oscClient.send_message("/live/clip/set/warp_mode", [0, i, 3]) # Pitch warping = 3
                else:
                    log.info("Chipmunk OFF")
                    for i in range(TOTAL_SONG_COUNT+1):
                        oscClient.send_message("/live/clip/set/warp_mode", [0, i, DEFAULT_WARPING_MODE]) # Complex pro warping = 6

            # Song selection change, start new track based on selection
            elif nodeId == SONG_SELECT_NODE_ID:
                songSelection = value

                if songSelection != lastSong:
                    log.info(f"Changing song to song: {songSelection}")

                    oscClient.send_message("/live/clip/start_listen/playing_position", [0, songSelection]) # Update clip listener to song
                    oscClient.send_message("/live/song/stop_all_clips", [])
                    oscClient.send_message("/live/song/stop_playing", [])

                    asyncio.create_task(launchScene(songSelection, calculateTempo(), 0))

                    log.info(f"New scene launched at beat: {currentPLCBeat}")
                    #oscClient.send_message("/live/song/set/current_song_time", float(currentPLCBeat))                            

                lastSong = songSelection

            # Volume setting from the PLC for the track, value is 0->100
            elif nodeId == VOLUME_NODE_ID:
                volume = value/100
                log.info(f"Volume (0-100%) updated to: {volume}")
                oscClient.send_message("/live/track/set/volume", [0, volume])

        except Exception as e:
            log.error(f"Subscription Error: {e}")

# opcTask handles the creation of the subscribes to OPCUA
# It also takes care of initial startup of a track in the program
async def opcTask():
    global PLCMasterSpeed
    global lastTempo
    global musicMutedForLowTempo

    handler = SubscriptionHandler()

    async with OpcUaClient(OPCUA_ENDPOINT) as opc:
        log.info("OPC UA connected")

        # Setup Nodes
        musicEnableNode = opc.get_node(MUSIC_ENABLE_NODE_ID)
        tempoNode = opc.get_node(TEMPO_NODE_ID)
        beatCountNode = opc.get_node(BEAT_COUNT_ID)
        volumeNode = opc.get_node(VOLUME_NODE_ID)
        songSelectNode = opc.get_node(SONG_SELECT_NODE_ID)
        chipmunkEnableNode = opc.get_node(CHIPMUNK_ENABLE_NODE_ID)
        heartbeatNode = opc.get_node(HEARTBEAT_NODE_ID)

        # Launch program heartbeat
        asyncio.create_task(heartbeatTask(heartbeatNode))

        # Read startup values
        PLCMasterSpeed = await tempoNode.read_value()

        # Set initial Ableton tempo
        tempo = calculateTempo()

        # If the tempo is not at a playable speed, wait until it is to start
        while tempo < 20:
            log.warning(f"Initial tempo too low ({tempo}) waiting...")
            musicMutedForLowTempo = True
            await asyncio.sleep(2)
            PLCMasterSpeed = await tempoNode.read_value()
            tempo = calculateTempo()

        oscClient.send_message("/live/song/set/tempo", tempo)
        lastTempo = tempo

        # Startup an empty scene in ableton to get it "warmed up" and able to properly respond to messages
        log.info("Starting up Empty Scene 0!")
        await launchScene(0, tempo, 0)
        await asyncio.sleep(3)

        # Create subscription
        subscription = await opc.create_subscription(30, handler)

        # Subcribe to data changes in the nodes
        await subscription.subscribe_data_change(musicEnableNode)
        await subscription.subscribe_data_change(tempoNode)
        await subscription.subscribe_data_change(beatCountNode)
        await subscription.subscribe_data_change(volumeNode)
        await subscription.subscribe_data_change(songSelectNode)
        await subscription.subscribe_data_change(chipmunkEnableNode)

        try:
            # While running check to make sure the tempo hasn't dropped too low
            while Running:
                if (
                    lowTempoStartTime is not None
                    and not musicMutedForLowTempo
                    and time.time() - lowTempoStartTime >= LOW_TEMPO_DELAY
                ):
                    log.warning("Muting Music - Tempo Low Too Long")
                    oscClient.send_message("/live/track/set/mute", [0, 1])
                    musicMutedForLowTempo = True

                await asyncio.sleep(0.1)

        except asyncio.CancelledError:
            pass

# Main contains the init for the entire program
# It sets ableton parameters for running and ensures everything is stopped and ready to go
async def main():
    global oscClient
    global Running

    # Ableton OSC Init
    oscClient = SimpleUDPClient(LOCAL_IP, ABLETONOSC_SEND_PORT)

    dispatcher = Dispatcher()
    dispatcher.map("/live/song/get/tempo", tempoCallback)
    dispatcher.map("/live/clip/get/playing_position", clipPositionCallback)

    server = ThreadingOSCUDPServer((LOCAL_IP, ABLETONOSC_RECEIVE_PORT), dispatcher)
    asyncio.get_running_loop().run_in_executor(None, server.serve_forever)
    log.info(f"Listening for AbletonOSC messages on port {ABLETONOSC_RECEIVE_PORT}")

    # Ensure nothing is already running
    oscClient.send_message("/live/song/stop_all_clips", [])
    oscClient.send_message("/live/song/stop_playing", [])                           

    oscClient.send_message("/live/song/get/tempo", [])
    oscClient.send_message("/live/clip/start_listen/playing_position", [0, 0])

    # Set project settings
    for i in range(TOTAL_SONG_COUNT+1): # Init settings for all scenes
        oscClient.send_message("/live/clip/set/loop_start", [0, i, 0.0]) #[track_index, clip_slot_index, value]
        oscClient.send_message("/live/clip/set/loop_end", [0, i, TOTAL_BEAT_COUNT])
        oscClient.send_message("/live/clip/set/looping", [0, i, 1]) # Turn looping on
        oscClient.send_message("/live/clip/set/warping", [0, i, 1]) # Turn warping on
        oscClient.send_message("/live/clip/set/warp_mode", [0, i, DEFAULT_WARPING_MODE]) # Complex pro warping = 6
        oscClient.send_message("/live/clip/set/ram_mode", [0, i, 1]) # Turn on RAM clip loading for better preformance
        asyncio.sleep(0.05) # Allow time for messages to be processed
    log.info("Track settings initialized")    
    await asyncio.sleep(4) # Allow time for messages to be processed
    oscClient.send_message("/live/song/set/current_song_time", 0) # Ensure set time is at 0 beats 

    try:
        await opcTask()

    except (KeyboardInterrupt, asyncio.CancelledError):
        log.error("Task stopped by user")

    finally:
        # Stop the program kill ableton and kill pythonOSC server
        Running = False
        oscClient.send_message("/live/song/set/current_song_time", 0)
        oscClient.send_message("/live/song/stop_playing", [])
        await asyncio.sleep(1)
        oscClient.send_message("/live/song/stop_all_clips", [])
        for i in range(TOTAL_SONG_COUNT+1):
            oscClient.send_message("/live/clip/stop_listen/playing_position", [0, i])
        oscClient.send_message("/live/song/set/nudge_up",0)
        oscClient.send_message("/live/song/set/nudge_down",0)

        log.info("Shutting down program...")
        logging.shutdown()
        server.shutdown()
        server.server_close()

if __name__ == "__main__":
    try:
        asyncio.run(main())

    except KeyboardInterrupt:
        pass