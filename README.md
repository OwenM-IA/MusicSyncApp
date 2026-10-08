"""
This program is designed to faciliate and align communication between the PLC and Ableton.

Libraries to install (can be done with pip install <lib-name>):*
 - asycuna
 - python_osc
*Only relevant if running the .py and not the .exe

To do this it uses AbletonOSC for the python<->ableton connection and asyncua (library built ontop of python-opcua) for PLC<->python (comms through opcUA*)
*OPCUA was added in RSLogix V36

This program works fundamentally by converting a master servo speed (controls the speed of the whole machine) into a BPM to assign a tempo to a song
and using gCell_BeatCount (a beatcount calculated in the PLC that covers a full cycle of the machine) to know when the beats in the song are supposed 
to occur. Small adjustments are made based on that to line up the song.
"""

"""
The log file that is created holds on the logs for the program: console.log

Config of the app can be set in the config.json file
config.json MUST be in the same folder as the exe
"""
