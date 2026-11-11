from odoo import api, fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    mdv_agri_imperial_units = fields.Boolean(related='company_id.mdv_agri_imperial_units', readonly=False)
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
    mdv_agri_frost_f = fields.Float('Frost Alert Below (F)', compute='_compute_imperial_thresholds', inverse='_inverse_frost_f')
    mdv_agri_heavy_rain_in = fields.Float('Heavy Rain Alert From (in/day)', compute='_compute_imperial_thresholds', inverse='_inverse_heavy_rain_in')
    mdv_agri_heat_f = fields.Float('Heat Alert From (F)', compute='_compute_imperial_thresholds', inverse='_inverse_heat_f')
    mdv_agri_wind_mph = fields.Float('Strong Wind Alert From (mph)', compute='_compute_imperial_thresholds', inverse='_inverse_wind_mph')
    mdv_agri_gdd_base_f = fields.Float('GDD Base Temperature (F)', compute='_compute_imperial_thresholds', inverse='_inverse_gdd_base_f')

    @api.depends('mdv_agri_frost_c', 'mdv_agri_heavy_rain_mm', 'mdv_agri_heat_c', 'mdv_agri_wind_kmh',
                 'mdv_agri_gdd_base_c')
    def _compute_imperial_thresholds(self):
        for settings in self:
            settings.mdv_agri_frost_f = settings.mdv_agri_frost_c * 9 / 5 + 32
            settings.mdv_agri_heavy_rain_in = settings.mdv_agri_heavy_rain_mm / 25.4
            settings.mdv_agri_heat_f = settings.mdv_agri_heat_c * 9 / 5 + 32
            settings.mdv_agri_wind_mph = settings.mdv_agri_wind_kmh * 0.6213711922
            settings.mdv_agri_gdd_base_f = settings.mdv_agri_gdd_base_c * 9 / 5 + 32

    def _inverse_frost_f(self):
        for settings in self:
            settings.mdv_agri_frost_c = (settings.mdv_agri_frost_f - 32) * 5 / 9

    def _inverse_heavy_rain_in(self):
        for settings in self:
            settings.mdv_agri_heavy_rain_mm = settings.mdv_agri_heavy_rain_in * 25.4

    def _inverse_heat_f(self):
        for settings in self:
            settings.mdv_agri_heat_c = (settings.mdv_agri_heat_f - 32) * 5 / 9

    def _inverse_wind_mph(self):
        for settings in self:
            settings.mdv_agri_wind_kmh = settings.mdv_agri_wind_mph / 0.6213711922

    def _inverse_gdd_base_f(self):
        for settings in self:
            settings.mdv_agri_gdd_base_c = (settings.mdv_agri_gdd_base_f - 32) * 5 / 9
