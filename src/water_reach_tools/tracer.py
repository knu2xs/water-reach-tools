import requests

_nhdplus_flowline_url = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6"

class HLNDI(object):
    """
    Hydro Network-Linked Data Index wrapper for my purposes.
    """
    def __init__(self):
        self._nhdplusurl