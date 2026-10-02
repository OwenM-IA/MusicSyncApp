# Grip Closed BPM Calculator
# BPM is calculated such that every Grip Closed event = 1 beat

import asyncio
import time

from asyncua import Client as OpcUaClient

OPCUA_ENDPOINT = "opc.tcp://192.168.2.2:4840"

GRIP_CLOSED_ID = (
    "ns=6;s=Program:Cell_S10_5_DialRobot."
    "Robot_Gripper_Close.Expected"
)

lastGripState = False
lastGripTime = None


class SubscriptionHandler:

    def datachange_notification(self, node, value, data):

        global lastGripState
        global lastGripTime

        try:

            #
            # Rising edge detection
            #
            if value and not lastGripState:

                currentTime = time.perf_counter()

                if lastGripTime is not None:

                    interval = (
                        currentTime - lastGripTime
                    )

                    bpm = 60.0 / interval

                    print(
                        f"Interval: {interval:.3f}s "
                        f"BPM: {bpm:.2f}"
                    )

                lastGripTime = currentTime

            lastGripState = value

        except Exception as e:

            print(
                "Subscription Error:",
                e
            )


async def main():

    handler = SubscriptionHandler()

    async with OpcUaClient(OPCUA_ENDPOINT) as opc:

        print("OPC UA Connected")

        gripNode = opc.get_node(
            GRIP_CLOSED_ID
        )

        subscription = (
            await opc.create_subscription(
                20,
                handler
            )
        )

        await subscription.subscribe_data_change(
            gripNode
        )

        print(
            f"Subscribed to {GRIP_CLOSED_ID}"
        )

        while True:

            await asyncio.sleep(1)


if __name__ == "__main__":

    asyncio.run(main())