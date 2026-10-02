import asyncio

from asyncua import Client


async def main():

    async with Client("opc.tcp://192.168.2.2:4840") as client:

        print("Connected!")

        node = client.get_node("ns=6;s=_gOBit")

        value = await node.read_value()

        print("_gOBit =", value)

if __name__ == "__main__":
    asyncio.run(main())