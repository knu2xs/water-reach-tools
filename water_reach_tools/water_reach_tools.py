"""Main module."""


class Reach(object):

    def __init__(self, reach_id):

        self.reach_id = str(reach_id)
        self.reach_name = ''
        self.reach_name_alternate = ''
        self.river_name = ''
        self.river_name_alternate = ''
        self.error = None                   # boolean
        self.notes = ''
        self.difficulty = ''
        self.difficulty_minimum = ''
        self.difficulty_maximum = ''
        self.difficulty_outlier = ''
        self.abstract = ''
        self.description = ''
        self.update_aw = None               # datetime
        self.update_arcgis = None           # datetime
        self.validated = None               # boolean
        self.validated_by = ''
        self._geometry = None
        self._reach_points = []
        self.agency = None
        self.gauge_observation = None
        self.gauge_id = None
        self.gauge_units = None
        self.gauge_metric = None
        self.gauge_r0 = None
        self.gauge_r1 = None
        self.gauge_r2 = None
        self.gauge_r3 = None
        self.gauge_r4 = None
        self.gauge_r5 = None
        self.gauge_r6 = None
        self.gauge_r7 = None
        self.gauge_r8 = None
        self.gauge_r9 = None
        self.tracing_method = None
        self.trace_source = None