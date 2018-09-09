DEPENDENCIES = ['eltako']

from .. import eltako

async def async_setup_platform(hass, config, add_entities, discovery_info=None):
    eltako.platforms['light'].set_result(add_entities)
