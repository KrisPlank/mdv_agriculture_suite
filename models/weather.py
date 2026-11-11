import logging
from datetime import datetime, timedelta

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

FORECAST_URL = 'https://api.open-meteo.com/v1/forecast'
ARCHIVE_URL = 'https://archive-api.open-meteo.com/v1/archive'
DAILY_VARS = [
    'temperature_2m_max', 'temperature_2m_min', 'temperature_2m_mean', 'precipitation_sum', 'rain_sum',
    'wind_speed_10m_max', 'wind_gusts_10m_max', 'relative_humidity_2m_mean', 'et0_fao_evapotranspiration',
    'weather_code',
]
FIELD_MAP = {
    'temperature_2m_max': 'temp_max_c', 'temperature_2m_min': 'temp_min_c', 'temperature_2m_mean': 'temp_mean_c',
    'precipitation_sum': 'precipitation_mm', 'rain_sum': 'rain_mm', 'wind_speed_10m_max': 'wind_max_kmh',
    'wind_gusts_10m_max': 'wind_gust_kmh', 'relative_humidity_2m_mean': 'humidity_pct',
    'et0_fao_evapotranspiration': 'et0_mm', 'weather_code': 'weather_code',
}
WMO = {
    0: 'Clear sky', 1: 'Mainly clear', 2: 'Partly cloudy', 3: 'Overcast', 45: 'Fog', 48: 'Rime fog',
    51: 'Light drizzle', 53: 'Drizzle', 55: 'Dense drizzle', 56: 'Freezing drizzle', 57: 'Freezing drizzle',
    61: 'Light rain', 63: 'Rain', 65: 'Heavy rain', 66: 'Freezing rain', 67: 'Freezing rain',
    71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 77: 'Snow grains', 80: 'Rain showers', 81: 'Rain showers',
    82: 'Violent rain showers', 85: 'Snow showers', 86: 'Snow showers', 95: 'Thunderstorm',
    96: 'Thunderstorm with hail', 99: 'Thunderstorm with hail',
}


class AgriWeatherLog(models.Model):
    _name = 'mdv.agri.weather.log'
    _description = 'Farm Weather Log'
    _order = 'date desc, farm_id'
    _rec_name = 'date'

    farm_id = fields.Many2one('mdv.agri.farm', required=True, ondelete='cascade', index=True)
    company_id = fields.Many2one(related='farm_id.company_id', store=True)
    date = fields.Date(required=True, index=True)
    source = fields.Selection([('manual', 'Manual'), ('open_meteo', 'Open-Meteo')], default='manual', required=True)
    is_forecast = fields.Boolean('Forecast')
    temp_min_c = fields.Float('Min Temp (C)', digits=(5, 1))
    temp_max_c = fields.Float('Max Temp (C)', digits=(5, 1))
    temp_mean_c = fields.Float('Mean Temp (C)', digits=(5, 1), aggregator='avg')
    precipitation_mm = fields.Float('Precipitation (mm)', digits=(6, 1))
    rain_mm = fields.Float('Rain (mm)', digits=(6, 1))
    humidity_pct = fields.Float('Humidity (%)', digits=(5, 1), aggregator='avg')
    wind_max_kmh = fields.Float('Max Wind (km/h)', digits=(6, 1), aggregator='max')
    wind_gust_kmh = fields.Float('Gusts (km/h)', digits=(6, 1), aggregator='max')
    et0_mm = fields.Float('ET0 (mm)', digits=(6, 2), help='Reference evapotranspiration (FAO-56).')
    weather_code = fields.Integer('WMO Code')
    condition = fields.Char(compute='_compute_condition')
    gdd = fields.Float('Growing Degree Days', compute='_compute_gdd', store=True, digits=(6, 1))
    frost_alert = fields.Boolean(compute='_compute_alerts', store=True)
    heavy_rain_alert = fields.Boolean(compute='_compute_alerts', store=True)
    heat_alert = fields.Boolean(compute='_compute_alerts', store=True)
    wind_alert = fields.Boolean(compute='_compute_alerts', store=True)
    has_alert = fields.Boolean(compute='_compute_alerts', store=True)
    alert_summary = fields.Char(compute='_compute_alerts', store=True)
    alert_notified = fields.Boolean(copy=False)
    notes = fields.Char()

    _farm_date_unique = models.Constraint('UNIQUE(farm_id, date)', 'There is already a weather log for this farm and day.')

    @api.constrains('humidity_pct', 'precipitation_mm')
    def _check_values(self):
        for log in self:
            if not 0 <= log.humidity_pct <= 100:
                raise ValidationError(_('Humidity must be between 0 and 100 %.'))
            if log.precipitation_mm < 0:
                raise ValidationError(_('Precipitation cannot be negative.'))

    def _compute_condition(self):
        for log in self:
            log.condition = WMO.get(log.weather_code, '') if log.source == 'open_meteo' or log.weather_code else ''

    def _gdd(self, base):
        self.ensure_one()
        return max(0.0, (self.temp_max_c + self.temp_min_c) / 2.0 - base)

    @api.depends('temp_max_c', 'temp_min_c', 'farm_id.company_id.mdv_agri_gdd_base_c')
    def _compute_gdd(self):
        for log in self:
            log.gdd = log._gdd(log.farm_id.company_id.mdv_agri_gdd_base_c or 10.0)

    @api.depends('temp_min_c', 'temp_max_c', 'precipitation_mm', 'wind_max_kmh', 'wind_gust_kmh', 'is_forecast')
    def _compute_alerts(self):
        for log in self:
            company = log.farm_id.company_id or self.env.company
            log.frost_alert = log.temp_min_c <= company.mdv_agri_frost_c
            log.heavy_rain_alert = log.precipitation_mm >= company.mdv_agri_heavy_rain_mm > 0
            log.heat_alert = log.temp_max_c >= company.mdv_agri_heat_c > 0
            log.wind_alert = max(log.wind_max_kmh, log.wind_gust_kmh) >= company.mdv_agri_wind_kmh > 0
            parts = []
            if log.frost_alert:
                parts.append(_('Frost %(t)s C', t=log.temp_min_c))
            if log.heavy_rain_alert:
                parts.append(_('Heavy rain %(mm)s mm', mm=log.precipitation_mm))
            if log.heat_alert:
                parts.append(_('Heat %(t)s C', t=log.temp_max_c))
            if log.wind_alert:
                parts.append(_('Wind %(w)s km/h', w=max(log.wind_max_kmh, log.wind_gust_kmh)))
            log.has_alert = bool(parts)
            log.alert_summary = ', '.join(parts)

    # ------------------------------------------------------------------ Open-Meteo
    @api.model
    def _open_meteo_get(self, url, params):
        try:
            response = requests.get(url, params=params, timeout=20)
        except requests.RequestException as err:
            raise UserError(_('Open-Meteo could not be reached: %s', err)) from err
        if response.status_code != 200:
            try:
                reason = response.json().get('reason')
            except ValueError:
                reason = response.text[:200]
            raise UserError(_('Open-Meteo returned an error: %s', reason))
        return response.json()

    @api.model
    def _store_open_meteo(self, farm, payload):
        """Create or update one log per day from an Open-Meteo daily payload."""
        daily = payload.get('daily') or {}
        days = daily.get('time') or []
        offset = payload.get('utc_offset_seconds') or 0
        local_today = (datetime.utcnow() + timedelta(seconds=offset)).date()
        existing = {log.date: log for log in self.search([('farm_id', '=', farm.id),
                                                          ('date', 'in', [fields.Date.to_date(d) for d in days])])}
        logs = self.browse()
        for idx, day in enumerate(days):
            date = fields.Date.to_date(day)
            vals = {'source': 'open_meteo', 'is_forecast': date > local_today}
            for key, fname in FIELD_MAP.items():
                values = daily.get(key)
                if values is not None and idx < len(values) and values[idx] is not None:
                    vals[fname] = values[idx]
            log = existing.get(date)
            if log:
                if log.source == 'manual':
                    logs |= log
                    continue
                log.write(vals)
            else:
                vals.update(farm_id=farm.id, date=date)
                log = self.create(vals)
            logs |= log
        return logs

    @api.model
    def fetch_open_meteo(self, farm, past_days=1, forecast_days=None):
        if not (farm.latitude or farm.longitude):
            raise UserError(_('Set the latitude and longitude of farm %s first.', farm.name))
        forecast_days = forecast_days if forecast_days is not None else (farm.company_id.mdv_agri_forecast_days or 3)
        payload = self._open_meteo_get(FORECAST_URL, {
            'latitude': farm.latitude, 'longitude': farm.longitude, 'daily': ','.join(DAILY_VARS),
            'timezone': 'auto', 'past_days': past_days, 'forecast_days': max(1, min(16, forecast_days + 1)),
        })
        logs = self._store_open_meteo(farm, payload)
        logs._notify_alerts()
        return logs

    @api.model
    def fetch_open_meteo_history(self, farm, date_from, date_to):
        if not (farm.latitude or farm.longitude):
            raise UserError(_('Set the latitude and longitude of farm %s first.', farm.name))
        if date_to < date_from:
            raise UserError(_('The end date must be after the start date.'))
        payload = self._open_meteo_get(ARCHIVE_URL, {
            'latitude': farm.latitude, 'longitude': farm.longitude, 'daily': ','.join(DAILY_VARS),
            'timezone': 'auto', 'start_date': fields.Date.to_string(date_from),
            'end_date': fields.Date.to_string(date_to),
        })
        return self._store_open_meteo(farm, payload)

    def _notify_alerts(self):
        today = fields.Date.context_today(self)
        for log in self.filtered(lambda l: l.has_alert and not l.alert_notified and l.date >= today):
            farm = log.farm_id
            label = _('Forecast') if log.is_forecast else _('Today')
            farm.message_post(body=_('%(label)s %(date)s: %(alerts)s', label=label, date=log.date,
                                     alerts=log.alert_summary), subtype_xmlid='mail.mt_note')
            if farm.manager_id:
                farm.activity_schedule('mail.mail_activity_data_warning', date_deadline=log.date,
                                       user_id=farm.manager_id.id,
                                       summary=_('Weather alert %(date)s: %(alerts)s', date=log.date,
                                                 alerts=log.alert_summary))
            log.alert_notified = True

    @api.model
    def _cron_fetch_weather(self):
        farms = self.env['mdv.agri.farm'].search([('active', '=', True)])
        for farm in farms:
            if not farm.company_id.mdv_agri_weather_auto or not (farm.latitude or farm.longitude):
                continue
            try:
                with self.env.cr.savepoint():
                    self.fetch_open_meteo(farm)
            except UserError as err:
                _logger.warning('Weather fetch failed for farm %s: %s', farm.name, err)


class AgriFarmWeather(models.Model):
    _inherit = 'mdv.agri.farm'

    weather_ids = fields.One2many('mdv.agri.weather.log', 'farm_id', string='Weather')

    def action_fetch_weather(self):
        logs = self.env['mdv.agri.weather.log']
        for farm in self:
            logs |= logs.fetch_open_meteo(farm)
        return {
            'type': 'ir.actions.client', 'tag': 'display_notification',
            'params': {'type': 'success', 'title': _('Weather updated'),
                       'message': _('%s days stored from Open-Meteo.', len(logs)),
                       'next': {'type': 'ir.actions.act_window_close'}},
        }
