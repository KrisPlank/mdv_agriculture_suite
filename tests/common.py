import json
from datetime import timedelta

from odoo import Command, fields
from odoo.tests import TransactionCase, new_test_user


def rect_geojson(lat, lng, dlat, dlng):
    ring = [[lng, lat], [lng + dlng, lat], [lng + dlng, lat + dlat], [lng, lat + dlat], [lng, lat]]
    return json.dumps({'type': 'Polygon', 'coordinates': [ring]})


class AgriCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.env = cls.env(context=dict(cls.env.context, tracking_disable=True, mail_notrack=True))
        cls.company = cls.env.company
        cls.company.write({'mdv_agri_allow_negative': False, 'mdv_agri_analytic': True,
                           'mdv_agri_labour_rate': 15.0, 'mdv_agri_machine_rate': 40.0,
                           'mdv_agri_frost_c': 0.0, 'mdv_agri_heavy_rain_mm': 25.0,
                           'mdv_agri_heat_c': 35.0, 'mdv_agri_wind_kmh': 60.0, 'mdv_agri_gdd_base_c': 10.0})
        cls.today = fields.Date.context_today(cls.env['mdv.agri.farm'])
        cls.warehouse = cls.env['stock.warehouse'].search([('company_id', '=', cls.company.id)], limit=1)
        cls.stock_loc = cls.warehouse.lot_stock_id
        uom_kg = cls.env.ref('uom.product_uom_kgm')
        uom_l = cls.env.ref('uom.product_uom_litre')
        uom_unit = cls.env.ref('uom.product_uom_unit')
        Product = cls.env['product.product']

        def product(name, uom, cost, price=0.0, tracking='none'):
            return Product.create({'name': name, 'type': 'consu', 'is_storable': True, 'uom_id': uom.id,
                                   'standard_price': cost, 'list_price': price, 'tracking': tracking})

        cls.vendor = cls.env['res.partner'].create({'name': 'Test Agro Supplier'})
        cls.customer = cls.env['res.partner'].create({'name': 'Test Grain Buyer', 'email': 'buyer@example.com'})
        cls.seed = product('T Seed', uom_kg, 0.5)
        cls.seed.seller_ids = [Command.create({'partner_id': cls.vendor.id, 'price': 0.5})]
        cls.fert = product('T Urea', uom_kg, 0.4)
        cls.fert.seller_ids = [Command.create({'partner_id': cls.vendor.id, 'price': 0.4})]
        cls.chem = product('T Fungicide', uom_l, 10.0)
        cls.grain = product('T Wheat Grain', uom_kg, 0.15, 0.25, tracking='lot')
        cls.milk = product('T Milk', uom_l, 0.3, 0.45)
        cls.eggs = product('T Eggs', uom_unit, 0.08, 0.15)
        cls.feed = product('T Dairy Feed', uom_kg, 0.4)
        cls.vaccine = product('T Vaccine', uom_unit, 1.0)
        cls.drug = product('T Antibiotic', uom_unit, 5.0)
        cls.company.write({'mdv_agri_milk_product_id': cls.milk.id, 'mdv_agri_egg_product_id': cls.eggs.id})
        Quant = cls.env['stock.quant']
        for prod, qty in [(cls.seed, 5000), (cls.fert, 5000), (cls.chem, 100), (cls.feed, 2000),
                          (cls.vaccine, 5000), (cls.drug, 20)]:
            Quant._update_available_quantity(prod, cls.stock_loc, qty)

        cls.employee = cls.env['hr.employee'].create({'name': 'Test Field Hand', 'hourly_cost': 20.0})
        cls.tractor = cls.env['maintenance.equipment'].create({
            'name': 'Test Tractor', 'mdv_agri_is_farm_machine': True, 'mdv_agri_hourly_rate': 50.0})

        cls.farm = cls.env['mdv.agri.farm'].create({
            'name': 'Test Farm', 'code': 'TF', 'latitude': 41.5, 'longitude': -93.6,
            'warehouse_id': cls.warehouse.id})
        cls.field = cls.env['mdv.agri.field'].create({
            'name': 'Test Field', 'code': 'F1', 'farm_id': cls.farm.id, 'area_ha': 10.0})
        cls.field2 = cls.env['mdv.agri.field'].create({
            'name': 'Leased Plot', 'code': 'F2', 'farm_id': cls.farm.id, 'area_ha': 4.0, 'tenure': 'leased',
            'lease_cost_per_season': 800.0})
        cls.season = cls.env['mdv.agri.season'].create({
            'name': 'Test Season', 'date_start': cls.today - timedelta(days=100),
            'date_end': cls.today + timedelta(days=200)})
        cls.crop = cls.env['mdv.agri.crop'].create({
            'name': 'Test Wheat', 'code': 'TW', 'product_id': cls.grain.id, 'growing_days': 150,
            'expected_yield_per_ha': 6000, 'base_temperature_c': 0.0,
            'template_line_ids': [
                Command.create({'name': 'Plough', 'activity_type': 'land_prep', 'day_offset': -10,
                                'labour_hours_per_ha': 0.5, 'machine_hours_per_ha': 1.0}),
                Command.create({'name': 'Drill', 'activity_type': 'sowing', 'day_offset': 0,
                                'product_id': cls.seed.id, 'qty_per_ha': 180, 'labour_hours_per_ha': 0.4}),
                Command.create({'name': 'Top dress', 'activity_type': 'fertilizer', 'day_offset': 60,
                                'product_id': cls.fert.id, 'qty_per_ha': 150}),
                Command.create({'name': 'Harvest', 'activity_type': 'harvest', 'day_offset': 150,
                                'machine_hours_per_ha': 0.7}),
            ]})
        cls.pest = cls.env['mdv.agri.pest'].create({
            'name': 'Test Rust', 'pest_type': 'disease', 'recommendation': 'Spray fungicide.',
            'treatment_line_ids': [Command.create({'product_id': cls.chem.id, 'rate_per_ha': 1.5})]})
        cls.grade_a = cls.env.ref('mdv_agriculture_suite.grade_a')
        cls.grade_b = cls.env.ref('mdv_agriculture_suite.grade_b')
        cls.cattle = cls.env.ref('mdv_agriculture_suite.species_cattle')
        cls.poultry = cls.env.ref('mdv_agriculture_suite.species_poultry')

        cls.agri_user = new_test_user(cls.env, login='agri_user_t', groups='mdv_agriculture_suite.group_agri_user')
        cls.agri_manager = new_test_user(cls.env, login='agri_mgr_t',
                                         groups='mdv_agriculture_suite.group_agri_manager,stock.group_stock_user')

    def _plan(self, field=None, sowing=None, confirm=True, **vals):
        plan = self.env['mdv.agri.crop.plan'].create(dict({
            'season_id': self.season.id, 'field_id': (field or self.field).id, 'crop_id': self.crop.id,
            'sowing_date': sowing or self.today - timedelta(days=5)}, **vals))
        if confirm:
            plan.action_confirm()
        return plan

    def _qty(self, product, location=None):
        return self.env['stock.quant']._get_available_quantity(product, location or self.stock_loc)
