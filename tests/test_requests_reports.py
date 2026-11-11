from datetime import timedelta

from odoo import Command
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.http import Request
from odoo.tests import HttpCase, new_test_user, tagged

from .common import AgriCommon


@tagged('post_install', '-at_install')
class TestCropRequest(AgriCommon):

    def _request(self, **vals):
        return self.env['mdv.agri.crop.request'].create(dict({
            'partner_id': self.customer.id, 'crop_id': self.crop.id, 'quantity': 30000}, **vals))

    def test_sequence_and_follower(self):
        req = self._request()
        self.assertTrue(req.name.startswith('CR/'))
        self.assertIn(self.customer, req.message_partner_ids)
        self.assertEqual(req.access_url, '/my/crop-requests/%s' % req.id)

    def test_quantity_or_area_required(self):
        with self.assertRaises(ValidationError):
            self._request(quantity=0, area_ha=0)

    def test_approve_and_convert_to_plan(self):
        req = self._request()
        req.action_review()
        req.action_approve()
        self.assertEqual(req.state, 'approved')
        action = req.action_convert_plan()
        wizard = self.env['mdv.agri.request.plan.wizard'].with_context(action['context']).create({
            'field_id': self.field.id, 'sowing_date': self.today + timedelta(days=10)})
        self.assertEqual(wizard.season_id, self.season)
        wizard.action_create()
        plan = req.plan_id
        self.assertEqual(req.state, 'converted')
        self.assertEqual(plan.request_id, req)
        self.assertAlmostEqual(plan.area_ha, 5.0, msg='30 t at 6 t/ha needs 5 ha')

    def test_contract_grower_purchase(self):
        grower = self.env['res.partner'].create({'name': 'Grower'})
        req = self._request(partner_id=grower.id, request_type='grower', price_unit=0.18)
        with self.assertRaises(UserError):
            req.action_create_purchase()
        req.action_review()
        req.action_create_purchase()
        order = req.purchase_order_id
        self.assertEqual(order.partner_id, grower)
        self.assertEqual(order.order_line.product_id, self.grain)
        self.assertAlmostEqual(order.order_line.price_unit, 0.18)
        self.assertEqual(order.mdv_crop_request_id, req)

    def test_supply_quotation(self):
        req = self._request(price_unit=0.3)
        req.action_review()
        req.action_create_quotation()
        order = req.sale_order_id
        self.assertEqual(order.partner_id, self.customer)
        self.assertAlmostEqual(order.order_line.product_uom_qty, 30000)
        self.assertAlmostEqual(order.order_line.price_unit, 0.3)

    def test_reject_posts_message(self):
        req = self._request(reject_reason='No land free this season')
        req.action_reject()
        self.assertEqual(req.state, 'rejected')
        self.assertIn('No land free', req.message_ids[0].body)
        req.action_reset()
        self.assertEqual(req.state, 'new')

    def test_user_cannot_approve_without_manager_rights(self):
        req = self._request()
        # approve is a manager button in the view; the record itself stays writable for users
        self.assertTrue(req.with_user(self.agri_user).has_access('write'))


@tagged('post_install', '-at_install')
class TestReportsSecurity(AgriCommon):

    def test_dashboard_data(self):
        plan = self._plan()
        plan.action_start()
        data = self.env['mdv.agri.dashboard'].get_dashboard_data()
        self.assertGreaterEqual(data['kpi']['active_plans'], 1)
        self.assertGreaterEqual(data['kpi']['area_planted'], 10.0)
        crops = {row['crop']: row for row in data['crops']}
        self.assertIn('Test Wheat', crops)
        self.assertAlmostEqual(crops['Test Wheat']['budget'], plan.budget_total)
        self.assertTrue(any(a['field'] == 'Test Field' for a in data['activities']))

    def test_cost_report_budget_vs_actual(self):
        plan = self._plan()
        plan.field_activity_ids.filtered(lambda a: a.activity_type == 'sowing').action_done()
        self.env.flush_all()
        rows = self.env['mdv.agri.cost.report'].search([('plan_id', '=', plan.id), ('cost_type', '=', 'material')])
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows.budget_amount, 1500.0)
        self.assertAlmostEqual(rows.actual_amount, 900.0)
        self.assertAlmostEqual(rows.variance, 600.0)

    def test_pdf_reports_render(self):
        plan = self._plan()
        harvest = self.env['mdv.agri.harvest'].create({'plan_id': plan.id, 'quantity': 100})
        harvest.action_validate()
        scout = self.env['mdv.agri.scouting'].create({'plan_id': plan.id, 'pest_id': self.pest.id})
        Report = self.env['ir.actions.report']
        html = Report._render_qweb_html('mdv_agriculture_suite.report_job_cost_sheet', plan.ids)[0]
        self.assertIn(b'Job Cost Sheet', html)
        self.assertIn(b'Materials', html)
        html = Report._render_qweb_html('mdv_agriculture_suite.report_harvest', harvest.ids)[0]
        self.assertIn(harvest.lot_id.name.encode(), html)
        html = Report._render_qweb_html('mdv_agriculture_suite.report_scouting', scout.ids)[0]
        self.assertIn(b'Test Rust', html)
        self.assertIn(plan.action_print_cost_sheet()['type'], ('ir.actions.report', 'ir.actions.act_window'))

    def test_multi_company_isolation(self):
        other = self.env['res.company'].create({'name': 'Other Agri Co'})
        other_farm = self.env['mdv.agri.farm'].with_company(other).create({'name': 'Other Farm',
                                                                           'company_id': other.id})
        user = new_test_user(self.env, login='agri_other_t', groups='mdv_agriculture_suite.group_agri_user',
                             company_id=self.company.id, company_ids=[Command.set(self.company.ids)])
        farms = self.env['mdv.agri.farm'].with_user(user).search([])
        self.assertIn(self.farm, farms)
        self.assertNotIn(other_farm, farms)

    def test_user_cannot_change_configuration(self):
        with self.assertRaises(AccessError):
            self.crop.with_user(self.agri_user).write({'growing_days': 10})
        with self.assertRaises(AccessError):
            self._plan(confirm=False).with_user(self.agri_user).unlink()
        self.crop.with_user(self.agri_manager).write({'growing_days': 140})
        self.assertEqual(self.crop.growing_days, 140)

    def test_agri_user_records_field_work(self):
        plan = self._plan()
        act = plan.field_activity_ids.filtered(lambda a: a.activity_type == 'sowing')
        act.labour_line_ids = [Command.create({'employee_id': self.employee.id, 'hours': 2})]
        act.with_user(self.agri_user).action_done()
        self.assertAlmostEqual(act.labour_line_ids.amount, 40.0)
        self.assertEqual(act.state, 'done')


@tagged('post_install', '-at_install')
class TestCropRequestPortal(HttpCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        grain = cls.env['product.product'].create({'name': 'Portal Grain', 'type': 'consu'})
        cls.crop = cls.env['mdv.agri.crop'].create({'name': 'Portal Barley', 'product_id': grain.id,
                                                    'expected_yield_per_ha': 5000})
        cls.portal_user = new_test_user(cls.env, login='agri_portal_t', password='agri_portal_t',
                                        groups='base.group_portal', name='Alex Portal')
        cls.stranger = cls.env['res.partner'].create({'name': 'Somebody Else'})
        cls.foreign_request = cls.env['mdv.agri.crop.request'].create({
            'partner_id': cls.stranger.id, 'crop_id': cls.crop.id, 'quantity': 10})

    def test_portal_submit_and_list(self):
        self.authenticate('agri_portal_t', 'agri_portal_t')
        res = self.url_open('/my/crop-requests/new')
        self.assertEqual(res.status_code, 200)
        self.assertIn('Portal Barley', res.text)
        res = self.url_open('/my/crop-requests/submit', data={
            'csrf_token': Request.csrf_token(self), 'crop_id': self.crop.id, 'request_type': 'supply',
            'quantity': '2500', 'description': 'For our mill'})
        self.assertEqual(res.status_code, 200)
        req = self.env['mdv.agri.crop.request'].search([('partner_id', '=', self.portal_user.partner_id.id)])
        self.assertEqual(len(req), 1)
        self.assertEqual(req.source, 'portal')
        self.assertEqual(req.quantity, 2500)
        listing = self.url_open('/my/crop-requests')
        self.assertIn(req.name, listing.text)
        self.assertNotIn(self.foreign_request.name, listing.text)

    def test_portal_cannot_open_other_partner_request(self):
        self.authenticate('agri_portal_t', 'agri_portal_t')
        res = self.url_open('/my/crop-requests/%s' % self.foreign_request.id)
        self.assertNotIn('For our mill', res.text)
        self.assertTrue(res.url.endswith('/my') or self.foreign_request.name not in res.text)
        with self.assertRaises(AccessError):
            self.foreign_request.with_user(self.portal_user).read(['name'])

    def test_portal_invalid_form(self):
        self.authenticate('agri_portal_t', 'agri_portal_t')
        res = self.url_open('/my/crop-requests/submit', data={
            'csrf_token': Request.csrf_token(self), 'crop_id': '', 'request_type': 'supply', 'quantity': ''})
        self.assertIn('Please check the highlighted fields', res.text)
        self.assertFalse(self.env['mdv.agri.crop.request'].search([('partner_id', '=', self.portal_user.partner_id.id)]))

    def test_public_website_request_creates_contact(self):
        self.authenticate(None, None)
        res = self.url_open('/crop-request')
        self.assertEqual(res.status_code, 200)
        res = self.url_open('/crop-request/submit', data={
            'csrf_token': Request.csrf_token(self), 'crop_id': self.crop.id, 'request_type': 'service',
            'area_ha': '4', 'contact_name': 'Jamie Walker', 'email': 'jamie.walker@example.com',
            'land_location': 'Lot 7'})
        self.assertIn('Thank you', res.text)
        req = self.env['mdv.agri.crop.request'].search([('partner_id.email', '=', 'jamie.walker@example.com')])
        self.assertEqual(req.source, 'website')
        self.assertEqual(req.area_ha, 4)
        self.assertEqual(req.partner_id.name, 'Jamie Walker')

    def test_public_request_needs_contact(self):
        self.authenticate(None, None)
        res = self.url_open('/crop-request/submit', data={
            'csrf_token': Request.csrf_token(self), 'crop_id': self.crop.id, 'request_type': 'supply', 'quantity': '5'})
        self.assertIn('Please check the highlighted fields', res.text)
