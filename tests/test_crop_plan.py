from datetime import timedelta

from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from .common import AgriCommon


@tagged('post_install', '-at_install')
class TestCropPlan(AgriCommon):

    def test_plan_defaults_from_field_and_crop(self):
        plan = self._plan(confirm=False)
        self.assertTrue(plan.name.startswith('CP/'))
        self.assertEqual(plan.area_ha, 10.0)
        self.assertEqual(plan.growing_days, 150)
        self.assertEqual(plan.expected_harvest_date, plan.sowing_date + timedelta(days=150))
        self.assertEqual(plan.expected_yield, 60000)

    def test_variety_overrides_crop_values(self):
        variety = self.env['mdv.agri.crop.variety'].create({
            'name': 'Fast', 'crop_id': self.crop.id, 'growing_days': 120, 'expected_yield_per_ha': 7000})
        plan = self._plan(confirm=False, variety_id=variety.id)
        self.assertEqual(plan.growing_days, 120)
        self.assertEqual(plan.expected_yield_per_ha, 7000)
        self.assertEqual(variety.display_name, 'Test Wheat - Fast')

    def test_confirm_generates_activities_from_template(self):
        plan = self._plan()
        self.assertEqual(plan.state, 'confirmed')
        acts = plan.field_activity_ids.sorted('date_planned')
        self.assertEqual(acts.mapped('activity_type'), ['land_prep', 'sowing', 'fertilizer', 'harvest'])
        self.assertEqual(acts[0].date_planned, plan.sowing_date - timedelta(days=10))
        sowing = acts.filtered(lambda a: a.activity_type == 'sowing')
        self.assertEqual(sowing.material_line_ids.product_id, self.seed)
        self.assertEqual(sowing.material_line_ids.quantity, 1800)
        self.assertAlmostEqual(sowing.material_line_ids.rate_per_ha, 180)
        self.assertAlmostEqual(acts[0].planned_machine_hours, 10.0)

    def test_confirm_builds_budget(self):
        plan = self._plan()
        material = plan.budget_line_ids.filtered(lambda b: b.cost_type == 'material')
        self.assertEqual(len(material), 2)
        self.assertAlmostEqual(sum(material.mapped('amount')), 1800 * 0.5 + 1500 * 0.4)
        labour = plan.budget_line_ids.filtered(lambda b: b.cost_type == 'labour')
        self.assertAlmostEqual(labour.quantity, 9.0)
        self.assertAlmostEqual(labour.amount, 9.0 * 15.0)
        machine = plan.budget_line_ids.filtered(lambda b: b.cost_type == 'machine')
        self.assertAlmostEqual(machine.amount, 17.0 * 40.0)
        self.assertAlmostEqual(plan.budget_total, 1500 + 135 + 680)

    def test_leased_field_adds_lease_to_budget_and_costs(self):
        plan = self._plan(field=self.field2)
        lease = plan.budget_line_ids.filtered(lambda b: b.cost_type == 'overhead')
        self.assertEqual(lease.amount, 800.0)
        plan.action_add_lease_cost()
        plan.action_add_lease_cost()
        self.assertEqual(plan.overhead_cost, 800.0, 'the lease is booked once')

    def test_confirm_creates_analytic_account(self):
        plan = self._plan()
        self.assertTrue(plan.analytic_account_id)
        self.assertEqual(plan.analytic_account_id.code, plan.name)
        self.company.mdv_agri_analytic = False
        plan2 = self._plan(field=self.field2)
        self.assertFalse(plan2.analytic_account_id)

    def test_overlapping_confirmed_plans_are_blocked(self):
        self._plan()
        second = self._plan(confirm=False, sowing=self.today + timedelta(days=20))
        with self.assertRaises(ValidationError):
            second.action_confirm()

    def test_draft_scenarios_may_overlap(self):
        self._plan()
        draft = self._plan(confirm=False, sowing=self.today + timedelta(days=20))
        self.assertEqual(draft.state, 'draft')
        later = self._plan(confirm=False, sowing=self.today + timedelta(days=200))
        later.action_confirm()
        self.assertEqual(later.state, 'confirmed')

    def test_planted_area_cannot_exceed_field(self):
        with self.assertRaises(ValidationError):
            self._plan(confirm=False, area_ha=12.0)

    def test_workflow_to_closed(self):
        plan = self._plan()
        plan.action_start()
        self.assertEqual(plan.state, 'growing')
        self.assertEqual(plan.actual_sowing_date, self.today)
        with self.assertRaises(UserError):
            plan.action_close()
        plan.action_mark_harvested()
        self.assertEqual(plan.harvest_end_date, self.today)
        plan.action_close()
        self.assertEqual(plan.state, 'closed')
        self.assertTrue(all(a.state == 'cancelled' for a in plan.field_activity_ids))

    def test_reset_to_draft_removes_planned_activities(self):
        plan = self._plan()
        plan.action_draft()
        self.assertEqual(plan.state, 'draft')
        self.assertFalse(plan.field_activity_ids)

    def test_cancel_blocked_after_work_done(self):
        plan = self._plan()
        act = plan.field_activity_ids.filtered(lambda a: a.activity_type == 'land_prep')
        act.action_done()
        with self.assertRaises(UserError):
            plan.action_cancel()

    def test_harvested_blocked_by_draft_harvest(self):
        plan = self._plan()
        self.env['mdv.agri.harvest'].create({'plan_id': plan.id, 'quantity': 100})
        with self.assertRaises(UserError):
            plan.action_mark_harvested()

    def test_cron_starts_sown_plans(self):
        plan = self._plan()
        sowing = plan.field_activity_ids.filtered(lambda a: a.activity_type == 'sowing')
        sowing.write({'state': 'done'})
        self.env['mdv.agri.crop.plan']._cron_start_due_plans()
        self.assertEqual(plan.state, 'growing')
