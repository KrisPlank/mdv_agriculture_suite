from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mdv_agri_frost_c = fields.Float(related='company_id.mdv_agri_frost_c', readonly=False)
    mdv_agri_heavy_rain_mm = fields.Float(related='company_id.mdv_agri_heavy_rain_mm', readonly=False)
    mdv_agri_heat_c = fields.Float(related='company_id.mdv_agri_heat_c', readonly=False)
    mdv_agri_wind_kmh = fields.Float(related='company_id.mdv_agri_wind_kmh', readonly=False)
    mdv_agri_gdd_base_c = fields.Float(related='company_id.mdv_agri_gdd_base_c', readonly=False)
    mdv_agri_weather_auto = fields.Boolean(related='company_id.mdv_agri_weather_auto', readonly=False)
    mdv_agri_forecast_days = fields.Integer(related='company_id.mdv_agri_forecast_days', readonly=False)
    mdv_agri_allow_negative = fields.Boolean(related='company_id.mdv_agri_allow_negative', readonly=False)
    mdv_agri_analytic = fields.Boolean(related='company_id.mdv_agri_analytic', readonly=False)
    mdv_agri_milk_product_id = fields.Many2one(related='company_id.mdv_agri_milk_product_id', readonly=False)
    mdv_agri_egg_product_id = fields.Many2one(related='company_id.mdv_agri_egg_product_id', readonly=False)
    mdv_agri_labour_rate = fields.Float(related='company_id.mdv_agri_labour_rate', readonly=False)
    mdv_agri_machine_rate = fields.Float(related='company_id.mdv_agri_machine_rate', readonly=False)
