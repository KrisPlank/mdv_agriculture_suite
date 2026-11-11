from datetime import timedelta
from unittest.mock import patch

import requests

from odoo import fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged
from odoo.tools import mute_logger

from .common import AgriCommon

GET = 'odoo.addons.mdv_agriculture_suite.models.weather.requests.get'


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status_code = status
        self.text = str(payload)

    def json(self):
        return self.payload


def open_meteo_payload(start, tmin, tmax, rain, offset=0):
    days = [fields.Date.to_string(start + timedelta(days=i)) for i in range(len(tmin))]
    return {
        'utc_offset_seconds': offset,
        'daily': {
            'time': days, 'temperature_2m_min': tmin, 'temperature_2m_max': tmax,
            'temperature_2m_mean': [(a + b) / 2 for a, b in zip(tmin, tmax)], 'precipitation_sum': rain,
            'rain_sum': rain, 'wind_speed_10m_max': [12.0] * len(tmin), 'wind_gusts_10m_max': [30.0] * len(tmin),
            'relative_humidity_2m_mean': [70] * len(tmin), 'et0_fao_evapotranspiration': [2.1] * len(tmin),
            'weather_code': [3] * len(tmin),
        },
    }


@tagged('post_install', '-at_install')
class TestScouting(AgriCommon):

    def setUp(self):
        super().setUp()
        self.plan = self._plan()

    def _scout(self, **vals):
        return self.env['mdv.agri.scouting'].create(dict({
            'plan_id': self.plan.id, 'pest_id': self.pest.id, 'severity': 'medium', 'affected_area_ha': 4.0}, **vals))

    def test_treatment_lines_from_pest_rate(self):
        scout = self._scout()
        self.assertTrue(scout.name.startswith('SC/'))
        self.assertEqual(scout.treatment_line_ids.product_id, self.chem)
        self.assertAlmostEqual(scout.treatment_line_ids.quantity, 6.0)
        self.assertEqual(scout.recommendation, 'Spray fungicide.')

    def test_whole_plan_area_when_affected_area_empty(self):
        scout = self._scout(affected_area_ha=0.0)
        self.assertAlmostEqual(scout.treatment_line_ids.quantity, 15.0)

    def test_create_spray_activity(self):
        scout = self._scout()
        scout.action_create_spray()
        act = scout.spray_activity_id
        self.assertEqual(act.activity_type, 'spraying')
        self.assertEqual(act.plan_id, self.plan)
        self.assertAlmostEqual(act.material_line_ids.quantity, 6.0)
        self.assertEqual(scout.state, 'reviewed')
        with self.assertRaises(UserError):
            scout.action_create_spray()
        act.action_done()
        self.assertEqual(scout.state, 'treated')
        self.assertAlmostEqual(self.plan.material_cost, 60.0)

    def test_high_severity_schedules_activity_for_responsible(self):
        scout = self._scout(severity='critical')
        self.assertEqual(scout.activity_ids.user_id, self.plan.responsible_id)
        low = self._scout(severity='low')
        self.assertFalse(low.activity_ids)

    def test_constraints(self):
        with self.assertRaises(ValidationError):
            self._scout(incidence_pct=150)
        with self.assertRaises(ValidationError):
            self._scout(affected_area_ha=50)

    def test_weather_of_the_day_is_shown(self):
        self.env['mdv.agri.weather.log'].create({'farm_id': self.farm.id, 'date': self.today, 'temp_max_c': 24.5,
                                                 'precipitation_mm': 3.0})
        scout = self._scout()
        self.assertAlmostEqual(scout.temp_max_c, 24.5)
        self.assertAlmostEqual(scout.precipitation_mm, 3.0)

    def test_imperial_weather_conversions_are_editable(self):
        self.company.mdv_agri_imperial_units = True
        scout = self._scout(affected_area_ha=2.0)
        self.assertAlmostEqual(scout.affected_area_acre, 2.0 * 2.4710538, places=4)
        scout.affected_area_acre = 1.0
        self.assertAlmostEqual(scout.affected_area_ha, 1.0 / 2.4710538, places=4)
        log = self.env['mdv.agri.weather.log'].create({
            'farm_id': self.farm.id, 'date': self.today, 'temp_max_c': 0.0, 'precipitation_mm': 25.4,
            'wind_max_kmh': 16.09344,
        })
        self.assertAlmostEqual(log.temp_max_f, 32.0)
        self.assertAlmostEqual(log.precipitation_in, 1.0)
        self.assertAlmostEqual(log.wind_max_mph, 10.0, places=3)
        log.temp_max_f = 50.0
        log.precipitation_in = 2.0
        log.wind_max_mph = 20.0
        self.assertAlmostEqual(log.temp_max_c, 10.0)
        self.assertAlmostEqual(log.precipitation_mm, 50.8)
        self.assertAlmostEqual(log.wind_max_kmh, 32.18688, places=3)


@tagged('post_install', '-at_install')
class TestWeather(AgriCommon):

    def _fetch(self, payload, status=200):
        with patch(GET, return_value=FakeResponse(payload, status)) as mocked:
            logs = self.env['mdv.agri.weather.log'].fetch_open_meteo(self.farm)
        return logs, mocked

    def test_fetch_creates_daily_logs_with_forecast_flag(self):
        start = self.today - timedelta(days=1)
        logs, mocked = self._fetch(open_meteo_payload(start, [4.0, 5.0, 6.0, 7.0], [15.0, 16.0, 17.0, 18.0],
                                                      [0.0, 1.0, 2.0, 0.0]))
        self.assertEqual(len(logs), 4)
        params = mocked.call_args.kwargs['params']
        self.assertEqual(params['latitude'], 41.5)
        self.assertIn('temperature_2m_max', params['daily'])
        self.assertEqual(logs.filtered(lambda l: l.date > self.today).mapped('is_forecast'), [True, True])
        self.assertFalse(logs.filtered(lambda l: l.date <= self.today).mapped('is_forecast')[0])
        self.assertTrue(all(src == 'open_meteo' for src in logs.mapped('source')))

    def test_refetch_updates_instead_of_duplicating(self):
        payload = open_meteo_payload(self.today, [4.0], [15.0], [0.0])
        self._fetch(payload)
        payload['daily']['temperature_2m_max'] = [19.0]
        self._fetch(payload)
        logs = self.env['mdv.agri.weather.log'].search([('farm_id', '=', self.farm.id)])
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs.temp_max_c, 19.0)

    def test_manual_log_is_not_overwritten(self):
        manual = self.env['mdv.agri.weather.log'].create({'farm_id': self.farm.id, 'date': self.today,
                                                          'temp_max_c': 11.0})
        self._fetch(open_meteo_payload(self.today, [4.0], [15.0], [0.0]))
        self.assertEqual(manual.temp_max_c, 11.0)
        self.assertEqual(manual.source, 'manual')

    def test_frost_and_heavy_rain_alerts_notify_manager_once(self):
        start = self.today
        logs, _m = self._fetch(open_meteo_payload(start, [-2.0, 6.0], [8.0, 14.0], [0.0, 40.0]))
        frost = logs.filtered(lambda l: l.date == start)
        rain = logs.filtered(lambda l: l.date == start + timedelta(days=1))
        self.assertTrue(frost.frost_alert)
        self.assertFalse(frost.heavy_rain_alert)
        self.assertTrue(rain.heavy_rain_alert)
        self.assertIn('Heavy rain', rain.alert_summary)
        self.assertTrue(frost.alert_notified and rain.alert_notified)
        warnings = self.farm.activity_ids.filtered(lambda a: 'Weather alert' in (a.summary or ''))
        self.assertEqual(len(warnings), 2)
        self.assertEqual(warnings.user_id, self.farm.manager_id)
        self._fetch(open_meteo_payload(start, [-2.0, 6.0], [8.0, 14.0], [0.0, 40.0]))
        self.assertEqual(len(self.farm.activity_ids.filtered(lambda a: 'Weather alert' in (a.summary or ''))), 2)

    def test_thresholds_come_from_settings(self):
        self.company.mdv_agri_heavy_rain_mm = 50.0
        logs, _m = self._fetch(open_meteo_payload(self.today, [5.0], [14.0], [40.0]))
        self.assertFalse(logs.heavy_rain_alert)

    def test_imperial_settings_convert_alert_thresholds(self):
        settings = self.env['res.config.settings'].create({'company_id': self.company.id})
        settings.mdv_agri_imperial_units = True
        self.assertTrue(self.company.mdv_agri_imperial_units)
        settings.mdv_agri_frost_f = 32.0
        self.assertAlmostEqual(self.company.mdv_agri_frost_c, 0.0)
        settings.mdv_agri_heavy_rain_in = 1.0
        self.assertAlmostEqual(self.company.mdv_agri_heavy_rain_mm, 25.4)

    def test_missing_coordinates(self):
        self.farm.write({'latitude': 0.0, 'longitude': 0.0})
        with self.assertRaises(UserError):
            self.env['mdv.agri.weather.log'].fetch_open_meteo(self.farm)

    def test_api_error_raises_user_error(self):
        with self.assertRaises(UserError):
            self._fetch({'error': True, 'reason': 'Latitude must be in range'}, status=400)
        with patch(GET, side_effect=requests.ConnectionError('offline')):
            with self.assertRaises(UserError):
                self.env['mdv.agri.weather.log'].fetch_open_meteo(self.farm)

    def test_cron_survives_api_failure(self):
        with patch(GET, side_effect=requests.ConnectionError('offline')):
            self.env['mdv.agri.weather.log']._cron_fetch_weather()
        self.assertFalse(self.env['mdv.agri.weather.log'].search([('farm_id', '=', self.farm.id)]))

    def test_history_wizard_uses_archive(self):
        start = self.today - timedelta(days=10)
        wizard = self.env['mdv.agri.weather.history.wizard'].create({
            'farm_ids': [(6, 0, self.farm.ids)], 'date_from': start, 'date_to': start + timedelta(days=2)})
        with patch(GET, return_value=FakeResponse(open_meteo_payload(start, [3.0, 4.0, 5.0], [12.0, 13.0, 14.0],
                                                                     [0.0, 0.0, 0.0]))) as mocked:
            wizard.action_load()
        self.assertIn('archive-api.open-meteo.com', mocked.call_args.args[0])
        self.assertEqual(mocked.call_args.kwargs['params']['start_date'], fields.Date.to_string(start))
        self.assertEqual(self.env['mdv.agri.weather.log'].search_count([('farm_id', '=', self.farm.id)]), 3)

    def test_gdd_and_rain_roll_up_to_plan(self):
        plan = self._plan(sowing=self.today - timedelta(days=3))
        plan.action_start()
        plan.actual_sowing_date = self.today - timedelta(days=3)
        Weather = self.env['mdv.agri.weather.log']
        for i, (tmin, tmax, rain) in enumerate([(2.0, 12.0, 5.0), (4.0, 16.0, 0.0), (6.0, 20.0, 10.0)]):
            Weather.create({'farm_id': self.farm.id, 'date': self.today - timedelta(days=3 - i),
                            'temp_min_c': tmin, 'temp_max_c': tmax, 'precipitation_mm': rain})
        Weather.create({'farm_id': self.farm.id, 'date': self.today + timedelta(days=1), 'is_forecast': True,
                        'temp_min_c': 10, 'temp_max_c': 30, 'precipitation_mm': 50})
        # base temperature of the crop is 0 C: 7 + 10 + 13
        self.assertAlmostEqual(plan.gdd_accumulated, 30.0)
        self.assertAlmostEqual(plan.rain_since_sowing_mm, 15.0)
        self.assertEqual(plan.days_since_sowing, 3)

    @mute_logger('odoo.sql_db')
    def test_one_log_per_farm_and_day(self):
        Weather = self.env['mdv.agri.weather.log']
        Weather.create({'farm_id': self.farm.id, 'date': self.today})
        with self.assertRaises(Exception):
            with self.env.cr.savepoint():
                Weather.create({'farm_id': self.farm.id, 'date': self.today})
                self.env.flush_all()
