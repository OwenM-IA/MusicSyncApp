import asyncio
from asyncua import Client, ua

ENDPOINT = "opc.tcp://192.168.2.2:4840"
NODE_ID = "ns=6;s=gCell_PythonProgHeartbeat"

async def main():
    async with Client(ENDPOINT) as client:

        node = client.get_node(NODE_ID)

        print("Current:", await node.read_value())

        dv = ua.DataValue()
        dv.Value = ua.Variant(True, ua.VariantType.Boolean)

        result = await node.write_attribute(
            ua.AttributeIds.Value,
            dv
        )

        print("Write complete")

asyncio.run(main())