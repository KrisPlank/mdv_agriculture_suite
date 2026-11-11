from odoo.exceptions import UserError, ValidationError
from odoo.tests import Form, tagged

from .common import AgriCommon


@tagged('post_install', '-at_install')
class TestHarvestSales(AgriCommon):

    def setUp(self):
        super().setUp()
        self.plan = self._plan()
        self.harvest = self.env['mdv.agri.harvest'].create({
            'plan_id': self.plan.id, 'quantity': 52000, 'grade_id': self.grade_b.id, 'moisture_pct': 13.5,
            'lot_name': 'TW-F1-2026-01'})

    def test_harvest_defaults(self):
        self.assertTrue(self.harvest.name.startswith('HV/'))
        self.assertEqual(self.harvest.product_id, self.grain)
        self.assertEqual(self.harvest.location_dest_id, self.stock_loc)
        self.assertAlmostEqual(self.harvest.yield_per_ha, 5200)

    def test_validate_creates_traceable_lot(self):
        self.harvest.action_validate()
        lot = self.harvest.lot_id
        self.assertEqual(lot.name, 'TW-F1-2026-01')
        self.assertEqual(lot.mdv_field_id, self.field)
        self.assertEqual(lot.mdv_season_id, self.season)
        self.assertEqual(lot.mdv_grade_id, self.grade_b)
        self.assertEqual(lot.mdv_crop_plan_id, self.plan)
        quant_qty = self.env['stock.quant']._get_available_quantity(self.grain, self.stock_loc, lot_id=lot)
        self.assertAlmostEqual(quant_qty, 52000)
        self.assertEqual(self.harvest.move_id.location_id.usage, 'production')

    def test_validate_updates_plan_yield(self):
        self.harvest.action_validate()
        self.assertEqual(self.plan.state, 'growing')
        self.assertAlmostEqual(self.plan.harvested_qty, 52000)
        self.assertAlmostEqual(self.plan.yield_per_ha, 5200)
        self.assertAlmostEqual(self.plan.yield_gap_pct, 52000 / 60000 * 100)

    def test_automatic_lot_number(self):
        harvest = self.env['mdv.agri.harvest'].create({'plan_id': self.plan.id, 'quantity': 10})
        harvest.action_validate()
        self.assertTrue(harvest.lot_id.name.startswith('TW-F1-'))

    def test_untracked_product_has_no_lot(self):
        self.grain.tracking = 'none'
        harvest = self.env['mdv.agri.harvest'].create({'plan_id': self.plan.id, 'quantity': 10})
        harvest.action_validate()
        self.assertFalse(harvest.lot_id)
        self.assertEqual(harvest.state, 'done')

    def test_constraints(self):
        with self.assertRaises(ValidationError):
            self.env['mdv.agri.harvest'].create({'plan_id': self.plan.id, 'quantity': 0})
        with self.assertRaises(ValidationError):
            self.harvest.moisture_pct = 120

    def _sell(self, qty=None):
        self.harvest.action_validate()
        action = self.harvest.action_create_sale_order()
        wizard = self.env['mdv.agri.harvest.sell.wizard'].with_context(action['context']).create(
            {'partner_id': self.customer.id})
        if qty is not None:
            wizard.line_ids.quantity = qty
        order = self.env['sale.order'].browse(wizard.action_create()['res_id'])
        return wizard, order

    def test_sell_wizard_prices_by_grade(self):
        wizard, order = self._sell()
        self.assertAlmostEqual(order.order_line.price_unit, round(0.25 * self.grade_b.price_factor, 2))
        self.assertEqual(order.order_line.mdv_lot_id, self.harvest.lot_id)
        self.assertEqual(order.order_line.mdv_crop_plan_id, self.plan)
        self.assertIn('TW-F1-2026-01', order.order_line.name)

    def test_confirmed_order_reserves_the_harvest_lot(self):
        other = self.env['stock.lot'].create({'name': 'OLD-LOT', 'product_id': self.grain.id})
        self.env['stock.quant']._update_available_quantity(self.grain, self.stock_loc, 1000, lot_id=other)
        _wizard, order = self._sell(qty=800)
        order.action_confirm()
        move_lines = order.order_line.move_ids.move_line_ids
        self.assertTrue(move_lines)
        self.assertEqual(move_lines.lot_id, self.harvest.lot_id)
        self.assertAlmostEqual(sum(move_lines.mapped('quantity')), 800)

    def test_revenue_and_margin_on_plan(self):
        _wizard, order = self._sell(qty=40000)
        order.action_confirm()
        self.assertAlmostEqual(self.plan.revenue, 40000 * round(0.25 * 0.85, 2))
        self.assertAlmostEqual(self.harvest.sold_qty, 40000)
        self.assertAlmostEqual(self.harvest.available_qty, 12000)
        self.assertAlmostEqual(self.plan.margin, self.plan.revenue - self.plan.total_cost)

    def test_cannot_oversell(self):
        self.harvest.action_validate()
        action = self.harvest.action_create_sale_order()
        wizard = self.env['mdv.agri.harvest.sell.wizard'].with_context(action['context']).create(
            {'partner_id': self.customer.id})
        wizard.line_ids.quantity = 60000
        with self.assertRaises(UserError):
            wizard.action_create()

    def test_sold_harvest_cannot_be_reset(self):
        _wizard, order = self._sell(qty=100)
        order.action_confirm()
        with self.assertRaises(UserError):
            self.harvest.action_reset()

    def test_reset_unsold_harvest_reverses_stock(self):
        self.harvest.action_validate()
        self.harvest.action_reset()
        self.assertEqual(self.harvest.state, 'draft')
        self.assertAlmostEqual(self.env['stock.quant']._get_available_quantity(self.grain, self.stock_loc), 0)

    def test_draft_harvest_cannot_be_sold(self):
        with self.assertRaises(UserError):
            self.harvest.action_create_sale_order()
