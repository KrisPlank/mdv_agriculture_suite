from odoo import fields, models, tools

from .cost import COST_TYPES


class AgriCostReport(models.Model):
    _name = 'mdv.agri.cost.report'
    _description = 'Farm Budget vs Actual'
    _auto = False
    _order = 'plan_id'

    plan_id = fields.Many2one('mdv.agri.crop.plan', readonly=True)
    season_id = fields.Many2one('mdv.agri.season', readonly=True)
    farm_id = fields.Many2one('mdv.agri.farm', readonly=True)
    field_id = fields.Many2one('mdv.agri.field', readonly=True)
    crop_id = fields.Many2one('mdv.agri.crop', readonly=True)
    company_id = fields.Many2one('res.company', readonly=True)
    cost_type = fields.Selection(COST_TYPES, readonly=True)
    budget_amount = fields.Float('Budget', readonly=True)
    actual_amount = fields.Float('Actual', readonly=True)
    variance = fields.Float('Budget - Actual', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT row_number() OVER () AS id, x.plan_id, p.season_id, p.farm_id, p.field_id, p.crop_id,
                       p.company_id, x.cost_type, SUM(x.budget) AS budget_amount, SUM(x.actual) AS actual_amount,
                       SUM(x.budget) - SUM(x.actual) AS variance
                FROM (
                    SELECT plan_id, cost_type, amount AS budget, 0.0 AS actual FROM mdv_agri_budget_line
                    UNION ALL
                    SELECT plan_id, cost_type, 0.0 AS budget, amount AS actual FROM mdv_agri_cost_line
                    WHERE plan_id IS NOT NULL
                ) x
                JOIN mdv_agri_crop_plan p ON p.id = x.plan_id
                GROUP BY x.plan_id, p.season_id, p.farm_id, p.field_id, p.crop_id, p.company_id, x.cost_type
            )""" % self._table)
