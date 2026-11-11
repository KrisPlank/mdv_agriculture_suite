import json

from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from odoo.addons.mdv_agriculture_suite.models.farm import polygon_ring, ring_area_ha

from .common import AgriCommon, rect_geojson


@tagged('post_install', '-at_install')
class TestFarmField(AgriCommon):

    def test_ring_area_matches_geometry(self):
        # 0.009 deg lat x 0.012 deg lng at 41.5 N is about 1.0 km x 1.0 km = 100 ha
        ring = polygon_ring(rect_geojson(41.5, -93.6, 0.009, 0.012))
        self.assertEqual(len(ring), 4, 'closing point is dropped')
        self.assertAlmostEqual(ring_area_ha(ring), 100.0, delta=1.5)

    def test_invalid_geojson_is_ignored(self):
        self.assertEqual(polygon_ring('not json'), [])
        self.assertEqual(polygon_ring(json.dumps({'type': 'Point', 'coordinates': [1, 2]})), [])
        self.assertEqual(ring_area_ha([]), 0.0)

    def test_field_boundary_sets_mapped_area_and_centroid(self):
        self.field.boundary_geojson = rect_geojson(41.5, -93.6, 0.0045, 0.006)
        self.assertAlmostEqual(self.field.map_area_ha, 25.0, delta=0.6)
        self.assertAlmostEqual(self.field.latitude, 41.50225, places=4)
        self.assertAlmostEqual(self.field.longitude, -93.597, places=4)
        self.field.action_use_mapped_area()
        self.assertAlmostEqual(self.field.area_ha, round(self.field.map_area_ha, 2))

    def test_area_in_acres(self):
        self.assertAlmostEqual(self.field.area_acre, 24.71, places=1)
        self.assertAlmostEqual(self.farm.total_area_ha, 14.0)

    def test_farm_map_collection_lists_mapped_fields(self):
        self.field.boundary_geojson = rect_geojson(41.5, -93.6, 0.002, 0.002)
        data = json.loads(self.farm.map_geojson)
        self.assertEqual(data['type'], 'FeatureCollection')
        self.assertEqual(len(data['features']), 1, 'only fields with a boundary are drawn')
        self.assertEqual(data['features'][0]['properties']['name'], 'Test Field')
        self.assertEqual(data['center'], [41.5, -93.6])

    def test_farm_location_defaults_to_warehouse_stock(self):
        self.assertEqual(self.farm.location_id, self.warehouse.lot_stock_id)
        self.assertEqual(self.farm._get_consumption_location(), self.stock_loc)

    def test_soil_test_updates_field(self):
        self.env['mdv.agri.soil.test'].create({'field_id': self.field.id, 'ph': 6.8, 'nitrogen_ppm': 21,
                                               'potassium_ppm': 150})
        self.assertEqual(self.field.soil_ph, 6.8)
        self.assertEqual(self.field.nitrogen_ppm, 21)
        self.assertEqual(self.field.potassium_ppm, 150)

    def test_constraints(self):
        with self.assertRaises(ValidationError):
            self.field.soil_ph = 15
        with self.assertRaises(ValidationError):
            self.farm.latitude = 95
        with self.assertRaises(ValidationError):
            self.field.area_ha = -1

    @mute_logger('odoo.sql_db')
    def test_field_code_unique_per_farm(self):
        with self.assertRaises(IntegrityError):
            self.env['mdv.agri.field'].create({'name': 'Dup', 'code': 'F1', 'farm_id': self.farm.id})
            self.env.flush_all()

    def test_field_state_follows_plan(self):
        self.assertEqual(self.field.state, 'fallow')
        plan = self._plan()
        self.assertEqual(self.field.state, 'planned')
        self.assertEqual(self.field.current_plan_id, plan)
        plan.action_start()
        self.assertEqual(self.field.state, 'growing')
        self.assertAlmostEqual(self.farm.cultivated_area_ha, 10.0)
