# Symphoni Music Synchronization Application

## Overview

The Symphoni Music Synchronization Application facilitates communication and synchronization between a PLC and Ableton Live.

The application acts as a bridge between the machine and music playback, allowing songs to automatically adjust their tempo and position to match machine operation in real time.

---

## How It Works

The application uses:

- **AbletonOSC** for communication between Python and Ableton Live
- **asyncua** (built on top of python-opcua) for communication between the PLC and Python using OPC UA

### Communication Flow

```text
PLC ⇄ OPC UA ⇄ Python Application ⇄ AbletonOSC ⇄ Ableton Live
```

### Synchronization Method

The synchronization process is based on two key PLC values:

#### Master Servo Speed

The machine's master virtual servo speed is used to calculate the song tempo (BPM).

The application continuously converts the machine speed into a BPM value and updates Ableton's tempo accordingly.

#### Beat Count (`gCell_BeatCount`)

`gCell_BeatCount` is a PLC-generated beat counter that represents the machine's position throughout a complete production cycle.

This value is used to determine where beats should occur within the song. The application compares the machine beat position against the song position and performs small timing corrections when necessary to keep the music synchronized with the machine.

---

## Requirements

### Running the Executable (.exe)

No additional software or Python libraries are required.

### Running from Source (.py)

Install the required Python libraries:

```bash
pip install asyncua
pip install python-osc
```

---

## OPC UA Requirements

The PLC must support OPC UA communication.

OPC UA server functionality was introduced in Studio 5000 Logix Designer Version 36 and newer.

---

## Configuration

Application settings are configured through:

```text
config.json
```

### Important

`config.json` must be located in the same folder as the executable (`.exe`) when running the packaged application.

Configuration values such as PLC connection settings, synchronization parameters, logging behavior, and song control options are stored in this file.

---

## Logging

The application automatically creates the following log file:

```text
console.log
```

This file contains:

- Application startup information
- PLC connection status
- Ableton connection status
- Synchronization events
- Warnings and errors
- Diagnostic information for troubleshooting

---

## Project Purpose

The goal of this application is to maintain real-time synchronization between industrial machine operation and music playback, allowing Ableton Live to dynamically follow machine speed while remaining phase-aligned with the machine's beat count throughout production.

---
