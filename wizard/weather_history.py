from datetime import timedelta

from odoo import _, fields, models


class AgriWeatherHistoryWizard(models.TransientModel):
    _name = 'mdv.agri.weather.history.wizard'
    _description = 'Load Weather History'

    farm_ids = fields.Many2many('mdv.agri.farm', required=True)
    date_from = fields.Date(required=True, default=lambda self: fields.Date.context_today(self) - timedelta(days=30))
    date_to = fields.Date(required=True, default=lambda self: fields.Date.context_today(self) - timedelta(days=2))

    def action_load(self):
        Weather = self.env['mdv.agri.weather.log']
        logs = Weather
        for farm in self.farm_ids:
            logs |= Weather.fetch_open_meteo_history(farm, self.date_from, self.date_to)
        return {'type': 'ir.actions.client', 'tag': 'display_notification',
                'params': {'type': 'success', 'title': _('Weather history loaded'),
                           'message': _('%s days stored from the Open-Meteo archive.', len(logs)),
                           'next': {'type': 'ir.actions.act_window_close'}}}
