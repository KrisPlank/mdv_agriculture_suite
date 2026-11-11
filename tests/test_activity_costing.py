from datetime import timedelta

from odoo import Command
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import AgriCommon


@tagged('post_install', '-at_install')
class TestActivityCosting(AgriCommon):

    def setUp(self):
        super().setUp()
        self.plan = self._plan()
        self.sowing = self.plan.field_activity_ids.filtered(lambda a: a.activity_type == 'sowing')
        self.sowing.write({
            'labour_line_ids': [Command.create({'employee_id': self.employee.id, 'hours': 4})],
            'machine_line_ids': [Command.create({'equipment_id': self.tractor.id, 'hours': 3})],
        })

    def test_done_consumes_stock_into_production(self):
        before = self._qty(self.seed)
        self.sowing.action_done()
        self.assertEqual(self.sowing.state, 'done')
        self.assertAlmostEqual(self._qty(self.seed), before - 1800)
        move = self.sowing.move_ids
        self.assertEqual(move.state, 'done')
        self.assertEqual(move.location_dest_id.usage, 'production')
        self.assertIn(self.plan.name, move.origin)

    def test_cost_lines_per_resource(self):
        self.sowing.action_done()
        costs = self.sowing.cost_line_ids
        self.assertAlmostEqual(costs.filtered(lambda c: c.cost_type == 'material').amount, 900.0)
        self.assertAlmostEqual(costs.filtered(lambda c: c.cost_type == 'labour').amount, 80.0,
                               msg='employee hourly cost is used')
        self.assertAlmostEqual(costs.filtered(lambda c: c.cost_type == 'machine').amount, 150.0)
        self.assertAlmostEqual(self.sowing.total_cost, 1130.0)
        self.assertAlmostEqual(self.plan.material_cost, 900.0)
        self.assertAlmostEqual(self.plan.direct_cost, 1130.0)

    def test_job_cost_sheet_figures(self):
        self.sowing.action_done()
        self.assertAlmostEqual(self.plan.total_cost, 1130.0)
        self.assertAlmostEqual(self.plan.cost_per_ha, 113.0)
        self.assertAlmostEqual(self.plan.budget_variance, self.plan.budget_total - 1130.0)
        rows = {r['label']: r for r in self.plan._cost_sheet_rows()}
        self.assertAlmostEqual(rows['Materials']['budget'], 1500.0)
        self.assertAlmostEqual(rows['Materials']['actual'], 900.0)
        self.assertAlmostEqual(rows['Materials']['variance'], 600.0)

    def test_costs_post_to_analytic_account(self):
        self.sowing.action_done()
        lines = self.env['account.analytic.line'].search([('account_id', '=', self.plan.analytic_account_id.id)])
        self.assertEqual(len(lines), 3)
        self.assertAlmostEqual(sum(lines.mapped('amount')), -1130.0)
        self.assertTrue(all(lines.mapped('mdv_agri_cost_line_id')))

    def test_bills_on_analytic_account_count_as_other_cost(self):
        self.env['account.analytic.line'].create({
            'name': 'Crop insurance', 'account_id': self.plan.analytic_account_id.id, 'amount': -250.0,
            'date': self.today})
        self.assertAlmostEqual(self.plan.other_cost, 250.0)
        self.assertAlmostEqual(self.plan.total_cost, 250.0)

    def test_not_enough_stock_is_refused(self):
        self.sowing.material_line_ids.quantity = 999999
        with self.assertRaises(UserError):
            self.sowing.action_done()
        self.assertEqual(self.sowing.state, 'planned')

    def test_negative_stock_allowed_by_setting(self):
        self.company.mdv_agri_allow_negative = True
        self.sowing.material_line_ids.quantity = 6000
        self.sowing.action_done()
        self.assertAlmostEqual(self.seed.with_context(location=self.stock_loc.id).qty_available, -1000.0)
        self.assertEqual(self.sowing.state, 'done')

    def test_undo_returns_stock_and_removes_costs(self):
        before = self._qty(self.seed)
        self.sowing.action_done()
        self.sowing.action_reset()
        self.assertEqual(self.sowing.state, 'planned')
        self.assertAlmostEqual(self._qty(self.seed), before)
        self.assertFalse(self.sowing.cost_line_ids)
        self.assertFalse(self.env['account.analytic.line'].search(
            [('account_id', '=', self.plan.analytic_account_id.id)]))

    def test_sowing_starts_plan_and_sets_actual_date(self):
        self.sowing.date_done = self.today - timedelta(days=2)
        self.sowing.action_done()
        self.assertEqual(self.plan.state, 'growing')
        self.assertEqual(self.plan.actual_sowing_date, self.today - timedelta(days=2))

    def test_activity_requires_confirmed_plan(self):
        draft = self._plan(field=self.field2, confirm=False)
        act = self.env['mdv.agri.activity'].create({'name': 'x', 'plan_id': draft.id, 'activity_type': 'other'})
        with self.assertRaises(UserError):
            act.action_done()

    def test_overdue_search(self):
        land = self.plan.field_activity_ids.filtered(lambda a: a.activity_type == 'land_prep')
        overdue = self.env['mdv.agri.activity'].search([('is_overdue', '=', True), ('plan_id', '=', self.plan.id)])
        self.assertIn(land, overdue)
        self.assertNotIn(self.plan.field_activity_ids.filtered(lambda a: a.activity_type == 'harvest'), overdue)

    def test_machine_hours_trigger_service_request(self):
        self.tractor.mdv_agri_service_hours = 2.0
        self.sowing.action_done()
        self.assertAlmostEqual(self.tractor.mdv_agri_hours_total, 3.0)
        request = self.env['maintenance.request'].search([('equipment_id', '=', self.tractor.id)])
        self.assertEqual(len(request), 1)
        self.assertEqual(request.maintenance_type, 'preventive')

    def test_irrigation_water_rolls_up(self):
        act = self.env['mdv.agri.activity'].create({'name': 'Water', 'plan_id': self.plan.id,
                                                   'activity_type': 'irrigation', 'water_m3': 450})
        act.action_done()
        self.assertEqual(self.plan.irrigation_m3, 450)

    def test_purchase_missing_materials(self):
        self.sowing.material_line_ids.quantity = 5500
        action = self.plan.action_purchase_materials()
        order = self.env['purchase.order'].browse(action['res_id'])
        self.assertEqual(order.partner_id, self.vendor)
        self.assertEqual(order.mdv_crop_plan_id, self.plan)
        line = order.order_line.filtered(lambda l: l.product_id == self.seed)
        self.assertAlmostEqual(line.product_qty, 500)
        self.assertFalse(order.order_line.filtered(lambda l: l.product_id == self.fert), 'fertiliser is in stock')
        self.assertEqual(self.plan.purchase_count, 1)

    def test_purchase_needs_vendor(self):
        self.sowing.material_line_ids.quantity = 5500
        self.seed.seller_ids.unlink()
        with self.assertRaises(UserError):
            self.plan.action_purchase_materials()
