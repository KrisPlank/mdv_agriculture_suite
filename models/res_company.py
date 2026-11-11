from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    mdv_agri_imperial_units = fields.Boolean('Use Imperial Units', default=False)
    mdv_agri_frost_c = fields.Float('Frost Alert Below (C)', default=0.0)
    mdv_agri_heavy_rain_mm = fields.Float('Heavy Rain Alert From (mm/day)', default=25.0)
    mdv_agri_heat_c = fields.Float('Heat Alert From (C)', default=35.0)
    mdv_agri_wind_kmh = fields.Float('Strong Wind Alert From (km/h)', default=60.0)
    mdv_agri_gdd_base_c = fields.Float('GDD Base Temperature (C)', default=10.0)
    mdv_agri_weather_auto = fields.Boolean('Fetch Weather Daily', default=True)
    mdv_agri_forecast_days = fields.Integer('Forecast Days', default=3)
    mdv_agri_allow_negative = fields.Boolean('Allow Consumption Without Stock', default=False)
    mdv_agri_analytic = fields.Boolean('Analytic Account per Crop Plan', default=True)
    mdv_agri_milk_product_id = fields.Many2one('product.product', 'Milk Product')
    mdv_agri_egg_product_id = fields.Many2one('product.product', 'Egg Product')
    mdv_agri_labour_rate = fields.Float('Default Labour Cost per Hour', default=15.0)
    mdv_agri_machine_rate = fields.Float('Default Machine Cost per Hour', default=40.0)
