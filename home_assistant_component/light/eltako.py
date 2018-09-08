import asyncio

DEPENDENCIES = ['eltako']

async def async_setup_platform(hass, config, add_entities, discovery_info=None):
    discovery_info['add_entities'].set_result(add_entities)
