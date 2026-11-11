import json
import math

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

EARTH_RADIUS_M = 6378137.0
HA_TO_ACRE = 2.4710538


def polygon_ring(geojson_text):
    """Return the outer ring of a GeoJSON polygon as [(lng, lat), ...] or []."""
    if not geojson_text:
        return []
    try:
        data = json.loads(geojson_text)
    except (TypeError, ValueError):
        return []
    if data.get('type') == 'Feature':
        data = data.get('geometry') or {}
    if data.get('type') != 'Polygon' or not data.get('coordinates'):
        return []
    ring = [(float(p[0]), float(p[1])) for p in data['coordinates'][0] if len(p) >= 2]
    if len(ring) > 1 and ring[0] == ring[-1]:
        ring = ring[:-1]
    return ring


def ring_area_ha(ring):
    """Geodesic area of a lng/lat ring in hectares (same formula as the map widget)."""
    if len(ring) < 3:
        return 0.0
    total = 0.0
    count = len(ring)
    for i in range(count):
        lng1, lat1 = ring[i]
        lng2, lat2 = ring[(i + 1) % count]
        total += math.radians(lng2 - lng1) * (2 + math.sin(math.radians(lat1)) + math.sin(math.radians(lat2)))
    return abs(total * EARTH_RADIUS_M * EARTH_RADIUS_M / 2.0) / 10000.0


class AgriFarm(models.Model):
    _name = 'mdv.agri.farm'
    _description = 'Farm'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mdv.agri.unit.mixin']
    _order = 'name'
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    code = fields.Char()
    active = fields.Boolean(default=True)
    color = fields.Integer()
    image = fields.Image(max_width=1024, max_height=1024)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    manager_id = fields.Many2one('res.users', 'Farm Manager', default=lambda self: self.env.user, tracking=True)
    partner_id = fields.Many2one('res.partner', 'Owner / Grower',
                                 help='Set for a contract grower farm owned by a partner farmer.')
    farm_type = fields.Selection([
        ('crop', 'Crop Farm'), ('livestock', 'Livestock Farm'), ('mixed', 'Mixed Farm'),
        ('dairy', 'Dairy Farm'), ('poultry', 'Poultry Farm'), ('orchard', 'Orchard / Plantation'),
        ('greenhouse', 'Greenhouse'),
    ], default='mixed', required=True)
    street = fields.Char()
    city = fields.Char()
    zip = fields.Char()
    state_id = fields.Many2one('res.country.state', domain="[('country_id', '=?', country_id)]")
    country_id = fields.Many2one('res.country')
    latitude = fields.Float(digits=(10, 6))
    longitude = fields.Float(digits=(10, 6))
    warehouse_id = fields.Many2one('stock.warehouse', check_company=True,
                                   default=lambda self: self.env['stock.warehouse'].search(
                                       [('company_id', '=', self.env.company.id)], limit=1))
    location_id = fields.Many2one(
        'stock.location', 'Farm Stock Location', check_company=True,
        domain="[('usage', '=', 'internal')]",
        help='Materials, feed and medicines are consumed from this location; harvests, milk and eggs are received into it.')
    field_ids = fields.One2many('mdv.agri.field', 'farm_id', string='Fields')
    field_count = fields.Integer(compute='_compute_counts')
    herd_ids = fields.One2many('mdv.agri.herd', 'farm_id', string='Herds and Flocks')
    herd_count = fields.Integer(compute='_compute_counts')
    animal_count = fields.Integer(compute='_compute_counts')
    plan_count = fields.Integer(compute='_compute_counts')
    weather_count = fields.Integer(compute='_compute_counts')
    total_area_ha = fields.Float('Total Area (ha)', compute='_compute_area', digits=(16, 2))
    total_area_acre = fields.Float('Total Area (acres)', compute='_compute_area', digits=(16, 2))
    cultivated_area_ha = fields.Float('Area Under Crop (ha)', compute='_compute_area', digits=(16, 2))
    cultivated_area_imperial = fields.Float(compute='_compute_area_imperial')
    map_geojson = fields.Text('Fields Map', compute='_compute_map_geojson')
    last_weather_id = fields.Many2one('mdv.agri.weather.log', compute='_compute_last_weather')
    notes = fields.Html()

    _code_company_unique = models.Constraint('UNIQUE(code, company_id)', 'The farm code must be unique per company.')

    @api.constrains('latitude', 'longitude')
    def _check_coordinates(self):
        for farm in self:
            if not -90 <= farm.latitude <= 90 or not -180 <= farm.longitude <= 180:
                raise ValidationError(_('Latitude must be between -90 and 90 and longitude between -180 and 180.'))

    @api.onchange('warehouse_id')
    def _onchange_warehouse_id(self):
        if self.warehouse_id and not self.location_id:
            self.location_id = self.warehouse_id.lot_stock_id

    @api.model_create_multi
    def create(self, vals_list):
        farms = super().create(vals_list)
        for farm in farms.filtered(lambda f: not f.location_id and f.warehouse_id):
            farm.location_id = farm.warehouse_id.lot_stock_id
        return farms

    def _compute_counts(self):
        Plan = self.env['mdv.agri.crop.plan']
        Animal = self.env['mdv.agri.animal']
        Weather = self.env['mdv.agri.weather.log']
        for farm in self:
            farm.field_count = len(farm.field_ids)
            farm.herd_count = len(farm.herd_ids)
            farm.animal_count = Animal.search_count([('farm_id', '=', farm.id), ('status', '=', 'active')])
            farm.plan_count = Plan.search_count([('farm_id', '=', farm.id)])
            farm.weather_count = Weather.search_count([('farm_id', '=', farm.id)])

    @api.depends('field_ids.area_ha', 'field_ids.state')
    def _compute_area(self):
        for farm in self:
            farm.total_area_ha = sum(farm.field_ids.mapped('area_ha'))
            farm.total_area_acre = farm.total_area_ha * HA_TO_ACRE
            farm.cultivated_area_ha = sum(farm.field_ids.filtered(lambda f: f.state == 'growing').mapped('area_ha'))

    @api.depends('total_area_ha', 'cultivated_area_ha')
    def _compute_area_imperial(self):
        for farm in self:
            farm.cultivated_area_imperial = farm.cultivated_area_ha * HA_TO_ACRE

    @api.depends('field_ids.boundary_geojson', 'field_ids.name', 'field_ids.area_ha', 'field_ids.state',
                 'field_ids.current_plan_id.crop_id.name', 'latitude', 'longitude',
                 'company_id.mdv_agri_imperial_units')
    def _compute_map_geojson(self):
        for farm in self:
            features = []
            for fld in farm.field_ids:
                ring = polygon_ring(fld.boundary_geojson)
                if not ring:
                    continue
                features.append({
                    'type': 'Feature',
                    'properties': {'name': fld.name, 'state': fld.state,
                                   'area': round(fld.area_acre if farm.company_id.mdv_agri_imperial_units
                                                 else fld.area_ha, 2),
                                   'area_unit': 'acres' if farm.company_id.mdv_agri_imperial_units else 'ha',
                                   'crop': fld.current_plan_id.crop_id.name or ''},
                    'geometry': {'type': 'Polygon', 'coordinates': [[list(p) for p in ring + ring[:1]]]},
                })
            farm.map_geojson = json.dumps({
                'type': 'FeatureCollection', 'features': features,
                'center': [farm.latitude, farm.longitude] if (farm.latitude or farm.longitude) else None,
            })

    def _compute_last_weather(self):
        Weather = self.env['mdv.agri.weather.log']
        today = fields.Date.context_today(self)
        for farm in self:
            farm.last_weather_id = Weather.search(
                [('farm_id', '=', farm.id), ('date', '<=', today)], order='date desc', limit=1)

    def _get_consumption_location(self):
        self.ensure_one()
        return self.location_id or self.warehouse_id.lot_stock_id

    def _action_open(self, xmlid, domain_field='farm_id'):
        action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
        action['domain'] = [(domain_field, '=', self.id)]
        action['context'] = {'default_%s' % domain_field: self.id}
        return action

    def action_open_fields(self):
        return self._action_open('mdv_agriculture_suite.action_agri_field')

    def action_open_plans(self):
        return self._action_open('mdv_agriculture_suite.action_agri_crop_plan')

    def action_open_herds(self):
        return self._action_open('mdv_agriculture_suite.action_agri_herd')

    def action_open_animals(self):
        return self._action_open('mdv_agriculture_suite.action_agri_animal')

    def action_open_weather(self):
        return self._action_open('mdv_agriculture_suite.action_agri_weather_log')


class AgriField(models.Model):
    _name = 'mdv.agri.field'
    _description = 'Field / Plot'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mdv.agri.unit.mixin']
    _order = 'farm_id, name'
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    code = fields.Char()
    active = fields.Boolean(default=True)
    color = fields.Integer()
    farm_id = fields.Many2one('mdv.agri.farm', required=True, ondelete='restrict', check_company=True, index=True)
    company_id = fields.Many2one(related='farm_id.company_id', store=True, index=True)
    area_ha = fields.Float('Area (ha)', digits=(16, 2), tracking=True)
    area_acre = fields.Float('Area (acres)', compute='_compute_area_acre', inverse='_inverse_area_acre', digits=(16, 2))
    map_area_ha = fields.Float('Mapped Area (ha)', compute='_compute_map', store=True, digits=(16, 2))
    map_area_acre = fields.Float('Mapped Area (acres)', compute='_compute_map_area_acre', digits=(16, 2))
    boundary_geojson = fields.Text('Boundary', help='Field boundary drawn on the map (GeoJSON polygon).')
    latitude = fields.Float(digits=(10, 6), compute='_compute_map', store=True, readonly=False)
    longitude = fields.Float(digits=(10, 6), compute='_compute_map', store=True, readonly=False)
    farm_latitude = fields.Float(related='farm_id.latitude', string='Farm Latitude')
    farm_longitude = fields.Float(related='farm_id.longitude', string='Farm Longitude')
    soil_type_id = fields.Many2one('mdv.agri.soil.type')
    soil_ph = fields.Float('Soil pH', digits=(4, 2))
    organic_matter = fields.Float('Organic Matter (%)', digits=(5, 2))
    nitrogen_ppm = fields.Float('Nitrogen (ppm)')
    phosphorus_ppm = fields.Float('Phosphorus (ppm)')
    potassium_ppm = fields.Float('Potassium (ppm)')
    irrigation_type = fields.Selection([
        ('rainfed', 'Rain-fed'), ('drip', 'Drip'), ('sprinkler', 'Sprinkler'), ('pivot', 'Centre Pivot'),
        ('flood', 'Flood / Furrow'),
    ], default='rainfed')
    tenure = fields.Selection([('owned', 'Owned'), ('leased', 'Leased'), ('contract', 'Contract Grower')],
                              default='owned')
    lease_cost_per_season = fields.Monetary('Lease Cost per Season', currency_field='currency_id')
    currency_id = fields.Many2one(related='company_id.currency_id')
    soil_test_ids = fields.One2many('mdv.agri.soil.test', 'field_id', string='Soil Tests')
    plan_ids = fields.One2many('mdv.agri.crop.plan', 'field_id', string='Crop Plans')
    current_plan_id = fields.Many2one('mdv.agri.crop.plan', compute='_compute_current_plan', store=True)
    state = fields.Selection([
        ('fallow', 'Fallow'), ('planned', 'Planned'), ('growing', 'Growing'), ('harvested', 'Harvested'),
    ], compute='_compute_current_plan', store=True)
    notes = fields.Html()

    _code_farm_unique = models.Constraint('UNIQUE(code, farm_id)', 'The field code must be unique per farm.')

    @api.constrains('area_ha')
    def _check_area(self):
        for fld in self:
            if fld.area_ha < 0:
                raise ValidationError(_('The field area cannot be negative.'))

    @api.constrains('soil_ph')
    def _check_ph(self):
        for fld in self:
            if fld.soil_ph and not 0 < fld.soil_ph <= 14:
                raise ValidationError(_('Soil pH must be between 0 and 14.'))

    @api.depends('area_ha')
    def _compute_area_acre(self):
        for fld in self:
            fld.area_acre = fld.area_ha * HA_TO_ACRE

    def _inverse_area_acre(self):
        for fld in self:
            fld.area_ha = fld.area_acre / HA_TO_ACRE

    @api.depends('map_area_ha')
    def _compute_map_area_acre(self):
        for fld in self:
            fld.map_area_acre = fld.map_area_ha * HA_TO_ACRE

    @api.depends('boundary_geojson')
    def _compute_map(self):
        for fld in self:
            ring = polygon_ring(fld.boundary_geojson)
            fld.map_area_ha = ring_area_ha(ring)
            if ring:
                fld.longitude = sum(p[0] for p in ring) / len(ring)
                fld.latitude = sum(p[1] for p in ring) / len(ring)

    @api.onchange('boundary_geojson')
    def _onchange_boundary(self):
        ring = polygon_ring(self.boundary_geojson)
        if ring and not self.area_ha:
            self.area_ha = round(ring_area_ha(ring), 2)

    @api.depends('plan_ids.state')
    def _compute_current_plan(self):
        order = {'growing': 0, 'confirmed': 1, 'harvested': 2}
        for fld in self:
            plans = fld.plan_ids.filtered(lambda p: p.state in order)
            plans = plans.sorted(lambda p: (order[p.state], -(p.sowing_date.toordinal() if p.sowing_date else 0)))
            plan = plans[:1]
            fld.current_plan_id = plan
            fld.state = {'growing': 'growing', 'confirmed': 'planned', 'harvested': 'harvested'}.get(
                plan.state, 'fallow')

    def action_use_mapped_area(self):
        for fld in self:
            if fld.map_area_ha:
                fld.area_ha = round(fld.map_area_ha, 2)

    def action_open_plans(self):
        action = self.env['ir.actions.act_window']._for_xml_id('mdv_agriculture_suite.action_agri_crop_plan')
        action['domain'] = [('field_id', '=', self.id)]
        action['context'] = {'default_field_id': self.id}
        return action


class AgriSoilTest(models.Model):
    _name = 'mdv.agri.soil.test'
    _description = 'Soil Test'
    _order = 'date desc'

    field_id = fields.Many2one('mdv.agri.field', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='field_id.company_id', store=True)
    date = fields.Date(required=True, default=fields.Date.context_today)
    lab_partner_id = fields.Many2one('res.partner', 'Laboratory')
    ph = fields.Float('pH', digits=(4, 2))
    organic_matter = fields.Float('Organic Matter (%)', digits=(5, 2))
    nitrogen_ppm = fields.Float('N (ppm)')
    phosphorus_ppm = fields.Float('P (ppm)')
    potassium_ppm = fields.Float('K (ppm)')
    ec = fields.Float('EC (dS/m)', digits=(6, 3))
    note = fields.Char()
    report_file = fields.Binary(attachment=True)
    report_filename = fields.Char()

    @api.model_create_multi
    def create(self, vals_list):
        tests = super().create(vals_list)
        tests._push_to_field()
        return tests

    def _push_to_field(self):
        """The latest soil test becomes the field's current soil data."""
        for test in self:
            latest = test.field_id.soil_test_ids.sorted('date', reverse=True)[:1]
            if latest == test:
                test.field_id.write({
                    'soil_ph': test.ph or test.field_id.soil_ph,
                    'organic_matter': test.organic_matter or test.field_id.organic_matter,
                    'nitrogen_ppm': test.nitrogen_ppm or test.field_id.nitrogen_ppm,
                    'phosphorus_ppm': test.phosphorus_ppm or test.field_id.phosphorus_ppm,
                    'potassium_ppm': test.potassium_ppm or test.field_id.potassium_ppm,
                })
