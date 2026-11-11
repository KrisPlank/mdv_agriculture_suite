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
    _inherit = ['mdv.agri.unit.mixin']
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
    temp_min_f = fields.Float('Min Temp (F)', compute='_compute_temp_f', inverse='_inverse_temp_min_f', digits=(5, 1))
    temp_max_f = fields.Float('Max Temp (F)', compute='_compute_temp_f', inverse='_inverse_temp_max_f', digits=(5, 1))
    temp_mean_f = fields.Float('Mean Temp (F)', compute='_compute_temp_f', inverse='_inverse_temp_mean_f', digits=(5, 1))
    precipitation_mm = fields.Float('Precipitation (mm)', digits=(6, 1))
    rain_mm = fields.Float('Rain (mm)', digits=(6, 1))
    precipitation_in = fields.Float('Precipitation (in)', compute='_compute_precipitation_in', inverse='_inverse_precipitation_in', digits=(6, 2))
    rain_in = fields.Float('Rain (in)', compute='_compute_precipitation_in', inverse='_inverse_rain_in', digits=(6, 2))
    humidity_pct = fields.Float('Humidity (%)', digits=(5, 1), aggregator='avg')
    wind_max_kmh = fields.Float('Max Wind (km/h)', digits=(6, 1), aggregator='max')
    wind_gust_kmh = fields.Float('Gusts (km/h)', digits=(6, 1), aggregator='max')
    wind_max_mph = fields.Float('Max Wind (mph)', compute='_compute_wind_mph', inverse='_inverse_wind_max_mph', digits=(6, 1))
    wind_gust_mph = fields.Float('Gusts (mph)', compute='_compute_wind_mph', inverse='_inverse_wind_gust_mph', digits=(6, 1))
    et0_mm = fields.Float('ET0 (mm)', digits=(6, 2), help='Reference evapotranspiration (FAO-56).')
    et0_in = fields.Float('ET0 (in)', compute='_compute_et0_in', inverse='_inverse_et0_in', digits=(6, 2))
    weather_code = fields.Integer('WMO Code')
    condition = fields.Char(compute='_compute_condition')
    gdd = fields.Float('Growing Degree Days', compute='_compute_gdd', store=True, digits=(6, 1))
    gdd_f = fields.Float('Growing Degree Days (F-days)', compute='_compute_gdd_f', digits=(6, 1))
    frost_alert = fields.Boolean(compute='_compute_alerts', store=True)
    heavy_rain_alert = fields.Boolean(compute='_compute_alerts', store=True)
    heat_alert = fields.Boolean(compute='_compute_alerts', store=True)
    wind_alert = fields.Boolean(compute='_compute_alerts', store=True)
    has_alert = fields.Boolean(compute='_compute_alerts', store=True)
    alert_summary = fields.Char(compute='_compute_alerts', store=True)
    alert_notified = fields.Boolean(copy=False)
    notes = fields.Char()

    _farm_date_unique = models.Constraint('UNIQUE(farm_id, date)', 'There is already a weather log for this farm and day.')

    @api.depends('temp_min_c', 'temp_max_c', 'temp_mean_c')
    def _compute_temp_f(self):
        for log in self:
            log.temp_min_f = log.temp_min_c * 9 / 5 + 32
            log.temp_max_f = log.temp_max_c * 9 / 5 + 32
            log.temp_mean_f = log.temp_mean_c * 9 / 5 + 32

    def _inverse_temp_min_f(self):
        for log in self:
            log.temp_min_c = (log.temp_min_f - 32) * 5 / 9

    def _inverse_temp_max_f(self):
        for log in self:
            log.temp_max_c = (log.temp_max_f - 32) * 5 / 9

    def _inverse_temp_mean_f(self):
        for log in self:
            log.temp_mean_c = (log.temp_mean_f - 32) * 5 / 9

    @api.depends('precipitation_mm', 'rain_mm')
    def _compute_precipitation_in(self):
        for log in self:
            log.precipitation_in = log.precipitation_mm / 25.4
            log.rain_in = log.rain_mm / 25.4

    def _inverse_precipitation_in(self):
        for log in self:
            log.precipitation_mm = log.precipitation_in * 25.4

    def _inverse_rain_in(self):
        for log in self:
            log.rain_mm = log.rain_in * 25.4

    @api.depends('wind_max_kmh', 'wind_gust_kmh')
    def _compute_wind_mph(self):
        for log in self:
            log.wind_max_mph = log.wind_max_kmh * 0.6213711922
            log.wind_gust_mph = log.wind_gust_kmh * 0.6213711922

    def _inverse_wind_max_mph(self):
        for log in self:
            log.wind_max_kmh = log.wind_max_mph / 0.6213711922

    def _inverse_wind_gust_mph(self):
        for log in self:
            log.wind_gust_kmh = log.wind_gust_mph / 0.6213711922

    @api.depends('et0_mm')
    def _compute_et0_in(self):
        for log in self:
            log.et0_in = log.et0_mm / 25.4

    def _inverse_et0_in(self):
        for log in self:
            log.et0_mm = log.et0_in * 25.4

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

    @api.depends('gdd')
    def _compute_gdd_f(self):
        for log in self:
            log.gdd_f = log.gdd * 9 / 5

    @api.depends('temp_min_c', 'temp_max_c', 'precipitation_mm', 'wind_max_kmh', 'wind_gust_kmh', 'is_forecast',
                 'farm_id.company_id.mdv_agri_imperial_units')
    def _compute_alerts(self):
        for log in self:
            company = log.farm_id.company_id or self.env.company
            log.frost_alert = log.temp_min_c <= company.mdv_agri_frost_c
            log.heavy_rain_alert = log.precipitation_mm >= company.mdv_agri_heavy_rain_mm > 0
            log.heat_alert = log.temp_max_c >= company.mdv_agri_heat_c > 0
            log.wind_alert = max(log.wind_max_kmh, log.wind_gust_kmh) >= company.mdv_agri_wind_kmh > 0
            parts = []
            imperial = company.mdv_agri_imperial_units
            if log.frost_alert:
                temp = log.temp_min_c * 9 / 5 + 32 if imperial else log.temp_min_c
                parts.append(_('Frost %(t)s %(unit)s', t=temp, unit='F' if imperial else 'C'))
            if log.heavy_rain_alert:
                rain = log.precipitation_mm / 25.4 if imperial else log.precipitation_mm
                parts.append(_('Heavy rain %(amount)s %(unit)s', amount=rain, unit='in' if imperial else 'mm'))
            if log.heat_alert:
                temp = log.temp_max_c * 9 / 5 + 32 if imperial else log.temp_max_c
                parts.append(_('Heat %(t)s %(unit)s', t=temp, unit='F' if imperial else 'C'))
            if log.wind_alert:
                wind = max(log.wind_max_kmh, log.wind_gust_kmh) * (0.6213711922 if imperial else 1)
                parts.append(_('Wind %(speed)s %(unit)s', speed=wind, unit='mph' if imperial else 'km/h'))
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
