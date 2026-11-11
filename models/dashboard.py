from datetime import timedelta

from odoo import api, fields, models


class AgriDashboard(models.AbstractModel):
    _name = 'mdv.agri.dashboard'
    _description = 'Farm Dashboard'

    @api.model
    def get_dashboard_data(self):
        """Figures for the farm dashboard, limited to the companies the user has selected."""
        env = self.env
        company_ids = env.companies.ids
        today = fields.Date.context_today(self)
        week = today - timedelta(days=6)
        currency = env.company.currency_id
        Plan = env['mdv.agri.crop.plan']
        plans = Plan.search([('company_id', 'in', company_ids), ('state', 'in', ('confirmed', 'growing'))])
        season_plans = Plan.search([('company_id', 'in', company_ids), ('state', '!=', 'cancelled'),
                                    ('season_id.date_start', '<=', today), ('season_id.date_end', '>=', today)])
        activities = env['mdv.agri.activity'].search([('company_id', 'in', company_ids), ('state', '=', 'planned'),
                                                      ('date_planned', '<=', today + timedelta(days=7))],
                                                     order='date_planned', limit=8)
        scouting = env['mdv.agri.scouting'].search([('company_id', 'in', company_ids),
                                                    ('state', 'in', ('draft', 'reviewed'))])
        alerts = env['mdv.agri.weather.log'].search([('company_id', 'in', company_ids), ('has_alert', '=', True),
                                                     ('date', '>=', today - timedelta(days=2))], order='date', limit=6)
        herds = env['mdv.agri.herd'].search([('company_id', 'in', company_ids)])
        milk = env['mdv.agri.milk.log'].search([('company_id', 'in', company_ids), ('date', '>=', week),
                                                ('date', '<=', today), ('discarded', '=', False)])
        eggs = env['mdv.agri.egg.log'].search([('company_id', 'in', company_ids), ('date', '>=', week),
                                               ('date', '<=', today)])
        harvests = env['mdv.agri.harvest'].search([('company_id', 'in', company_ids), ('state', '=', 'done'),
                                                   ('plan_id', 'in', season_plans.ids)])
        due_vet = env['mdv.agri.vet.treatment'].search_count([('company_id', 'in', company_ids),
                                                              ('state', '=', 'planned'),
                                                              ('date', '<=', today + timedelta(days=7))])
        requests = env['mdv.agri.crop.request'].search_count([('company_id', 'in', company_ids),
                                                              ('state', 'in', ('new', 'review'))])
        by_crop = {}
        for plan in season_plans:
            row = by_crop.setdefault(plan.crop_id.name, {'crop': plan.crop_id.name, 'area': 0.0, 'budget': 0.0,
                                                         'actual': 0.0, 'harvested': 0.0,
                                                         'uom': plan.crop_id.yield_uom_id.name or ''})
            row['area'] += plan.area_ha
            row['budget'] += plan.budget_total
            row['actual'] += plan.direct_cost
            row['harvested'] += plan.harvested_qty
        severity_order = {'critical': 0, 'high': 1, 'medium': 2, 'low': 3}
        return {
            'currency': {'symbol': currency.symbol, 'position': currency.position},
            'kpi': {
                'farms': env['mdv.agri.farm'].search_count([('company_id', 'in', company_ids)]),
                'area_planted': round(sum(plans.mapped('area_ha')), 2),
                'active_plans': len(plans),
                'season_budget': round(sum(season_plans.mapped('budget_total')), 2),
                'season_actual': round(sum(season_plans.mapped('direct_cost')), 2),
                'season_harvest': round(sum(harvests.mapped('quantity')), 2),
                'season_harvest_lots': len(harvests),
                'open_scouting': len(scouting),
                'critical_scouting': len(scouting.filtered(lambda s: s.severity in ('high', 'critical'))),
                'animals': sum(herds.mapped('current_count')),
                'milk_7d': round(sum(milk.mapped('quantity_l')), 1),
                'eggs_7d': sum(eggs.mapped('eggs_collected')),
                'vet_due': due_vet,
                'requests': requests,
            },
            'activities': [{'id': a.id, 'name': a.name, 'type': dict(a._fields['activity_type'].selection)[a.activity_type],
                            'field': a.field_id.name, 'date': fields.Date.to_string(a.date_planned),
                            'overdue': a.date_planned < today} for a in activities],
            'alerts': [{'id': w.id, 'farm': w.farm_id.name, 'date': fields.Date.to_string(w.date),
                        'summary': w.alert_summary, 'forecast': w.is_forecast} for w in alerts],
            'scouting': [{'id': s.id, 'name': s.name, 'pest': s.pest_id.name, 'field': s.field_id.name,
                          'severity': s.severity}
                         for s in scouting.sorted(lambda s: severity_order.get(s.severity, 9))[:6]],
            'crops': sorted(by_crop.values(), key=lambda r: -r['area']),
        }
