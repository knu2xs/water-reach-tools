# coding: utf-8
from multiprocessing import Pool
import os
import sys

from arcgis.gis import GIS
from dotenv import load_dotenv
from tqdm.notebook import tqdm

sys.path.append('../')

from water_reach_tools import Reach
from water_reach_tools.water_reach_tools import ReachLineFeatureLayer, ReachPointFeatureLayer

# processor count to utilize
num_processors = 32

load_dotenv('../.env')


# define a worker function — a function which will be executed in parallel
def update_stages(rid):
    """Update reach attributes, but ignore geometry."""
    print(f'Starting {rid}')
    rch = Reach.get_from_aw(rid)
    line_lyr.update_stage(rch)
    centroid_lyr.update_stage(rch)
    print(f'Finished {rid}')


if __name__ == '__main__':

    gis = GIS(
        url=os.getenv('ARCGIS_URL', 'https://arcgis.com'),
        username=os.getenv('ARCGIS_USERNAME', None),
        password=os.getenv('ARCGIS_PASSWORD', None)
    )

    line_lyr = ReachLineFeatureLayer.from_item_id(gis, os.getenv('REACH_LINE_ID'))
    centroid_lyr = ReachPointFeatureLayer.from_item_id(gis, os.getenv('REACH_CENTROID_ID'))

    # get a list of unique values
    reach_id_lst = line_lyr.get_unique_values('reach_id', 'gauge_id IS NOT NULL')

    # Create a pool of processors
    p = Pool(processes=num_processors)

    #get them to work in parallel
    output = p.map(update_stages, reach_id_lst)
