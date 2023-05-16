from .bus import BusInterface

import aiocoap

class CoAPInterface(BusInterface):
    def __init__(self, context, address):
        self.context = context
        self.address = address

    async def base_exchange(self, request):
        coap_request = aiocoap.Message(code=aiocoap.POST, uri=self.address, payload=request.serialize())
        coap_response = await self.context.request(coap_request).response

        if coap_response.code != aiocoap.CONTENT:
            raise Exception("Unsuccessful response: %s %s"%(coap_response, coap_response.payload))

        return coap_response.payload

    async def read_mem(self, address):
        # FIXME this is not how URIs work
        coap_request = aiocoap.Message(code=aiocoap.GET, uri=self.address.replace('raw', 'memory') + '?addr=%d'%address)
        coap_response = await self.context.request(coap_request).response

        full = coap_response.payload

        row_length = 8
        row_number = 256
        assert len(full) == row_length * row_number

        return tuple(full[i*row_length:(i+1)*row_length] for i in range(row_number))
