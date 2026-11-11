from collections import defaultdict
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import float_compare


class AgriCropPlan(models.Model):
    _name = 'mdv.agri.crop.plan'
    _description = 'Crop Plan'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mdv.agri.unit.mixin']
    _order = 'sowing_date desc, id desc'
    _check_company_auto = True

    name = fields.Char(required=True, copy=False, readonly=True, default=lambda self: _('New'))
    state = fields.Selection([
        ('draft', 'Draft'), ('confirmed', 'Planned'), ('growing', 'Growing'),
        ('harvested', 'Harvested'), ('closed', 'Closed'), ('cancelled', 'Cancelled'),
    ], default='draft', required=True, tracking=True, copy=False)
    season_id = fields.Many2one('mdv.agri.season', required=True, tracking=True)
    field_id = fields.Many2one('mdv.agri.field', required=True, tracking=True, check_company=True, index=True)
    farm_id = fields.Many2one(related='field_id.farm_id', store=True, index=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one(related='company_id.currency_id')
    crop_id = fields.Many2one('mdv.agri.crop', required=True, tracking=True)
    variety_id = fields.Many2one('mdv.agri.crop.variety', domain="[('crop_id', '=', crop_id)]")
    responsible_id = fields.Many2one('res.users', default=lambda self: self.env.user, tracking=True)
    area_ha = fields.Float('Planted Area (ha)', digits=(16, 2), compute='_compute_area_ha', store=True,
                           readonly=False, tracking=True)
    area_acre = fields.Float('Planted Area (acres)', compute='_compute_area_acre', inverse='_inverse_area_acre', digits=(16, 2))
    sowing_date = fields.Date('Planned Sowing', required=True, default=fields.Date.context_today, tracking=True)
    actual_sowing_date = fields.Date('Actual Sowing', copy=False)
    growing_days = fields.Integer(compute='_compute_growing_days', store=True, readonly=False)
    expected_harvest_date = fields.Date(compute='_compute_expected_harvest_date', store=True, readonly=False)
    harvest_end_date = fields.Date('Harvest Finished', copy=False)
    expected_yield_per_ha = fields.Float(compute='_compute_expected_yield', store=True, readonly=False,
                                         digits=(16, 2))
    expected_yield_per_acre = fields.Float('Expected Yield per acre', compute='_compute_expected_yield_per_acre',
                                           inverse='_inverse_expected_yield_per_acre', digits=(16, 2))
    expected_yield = fields.Float(compute='_compute_expected_yield_total', store=True, digits=(16, 2))
    yield_uom_id = fields.Many2one(related='crop_id.yield_uom_id')
    analytic_account_id = fields.Many2one('account.analytic.account', copy=False, check_company=True)
    request_id = fields.Many2one('mdv.agri.crop.request', 'Crop Request', copy=False)
    notes = fields.Html()

    field_activity_ids = fields.One2many('mdv.agri.activity', 'plan_id', string='Field Activities')
    harvest_ids = fields.One2many('mdv.agri.harvest', 'plan_id', string='Harvests')
    scouting_ids = fields.One2many('mdv.agri.scouting', 'plan_id', string='Scouting')
    budget_line_ids = fields.One2many('mdv.agri.budget.line', 'plan_id', string='Budget Lines', copy=True)
    cost_line_ids = fields.One2many('mdv.agri.cost.line', 'plan_id', string='Actual Costs')
    sale_line_ids = fields.One2many('sale.order.line', 'mdv_crop_plan_id', string='Sales Lines')
    field_activity_count = fields.Integer(compute='_compute_counts')
    harvest_count = fields.Integer(compute='_compute_counts')
    scouting_count = fields.Integer(compute='_compute_counts')
    open_scouting_count = fields.Integer('Open Scouting', compute='_compute_counts')
    sale_order_count = fields.Integer(compute='_compute_counts')
    purchase_count = fields.Integer(compute='_compute_counts')

    material_cost = fields.Monetary(compute='_compute_costs', store=True)
    labour_cost = fields.Monetary(compute='_compute_costs', store=True)
    machine_cost = fields.Monetary(compute='_compute_costs', store=True)
    overhead_cost = fields.Monetary(compute='_compute_costs', store=True)
    direct_cost = fields.Monetary('Direct Cost', compute='_compute_costs', store=True)
    other_cost = fields.Monetary('Bills and Expenses', compute='_compute_other_cost',
                                 help='Vendor bills and expenses booked on the analytic account of this plan.')
    total_cost = fields.Monetary(compute='_compute_other_cost')
    budget_total = fields.Monetary('Budget', compute='_compute_budget', store=True)
    budget_variance = fields.Monetary('Variance', compute='_compute_other_cost',
                                      help='Budget minus actual cost: negative means over budget.')
    budget_used_pct = fields.Float('Budget Used (%)', compute='_compute_other_cost')
    cost_per_ha = fields.Monetary('Cost per ha', compute='_compute_other_cost')
    cost_per_acre = fields.Monetary('Cost per acre', compute='_compute_cost_per_acre')
    harvested_qty = fields.Float(compute='_compute_harvest', store=True, digits=(16, 2))
    yield_per_ha = fields.Float('Yield per ha', compute='_compute_harvest', store=True, digits=(16, 2))
    yield_per_acre = fields.Float('Yield per acre', compute='_compute_yield_per_acre', digits=(16, 2))
    yield_gap_pct = fields.Float('Yield vs Expected (%)', compute='_compute_harvest', store=True)
    cost_per_unit = fields.Monetary('Cost per Unit of Yield', compute='_compute_other_cost')
    revenue = fields.Monetary(compute='_compute_revenue', store=True)
    margin = fields.Monetary(compute='_compute_other_cost')
    days_since_sowing = fields.Integer(compute='_compute_agronomy')
    progress_pct = fields.Float('Season Progress (%)', compute='_compute_agronomy')
    gdd_accumulated = fields.Float('Growing Degree Days', compute='_compute_agronomy', digits=(16, 1))
    gdd_accumulated_f = fields.Float('Growing Degree Days (F-days)', compute='_compute_gdd_accumulated_f', digits=(16, 1))
    rain_since_sowing_mm = fields.Float('Rain Since Sowing (mm)', compute='_compute_agronomy', digits=(16, 1))
    rain_since_sowing_in = fields.Float('Rain Since Sowing (in)', compute='_compute_rain_since_sowing_in', digits=(16, 2))
    irrigation_m3 = fields.Float('Irrigation Water (m3)', compute='_compute_agronomy', digits=(16, 1))
    irrigation_us_gal = fields.Float('Irrigation Water (US gal)', compute='_compute_irrigation_us_gal', digits=(16, 1))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('mdv.agri.crop.plan') or _('New')
        return super().create(vals_list)

    # ------------------------------------------------------------------ computes
    @api.depends('field_id')
    def _compute_area_ha(self):
        for plan in self:
            if not plan.area_ha:
                plan.area_ha = plan.field_id.area_ha

    @api.depends('area_ha')
    def _compute_area_acre(self):
        for plan in self:
            plan.area_acre = plan.area_ha * 2.4710538

    def _inverse_area_acre(self):
        for plan in self:
            plan.area_ha = plan.area_acre / 2.4710538

    @api.depends('irrigation_m3')
    def _compute_irrigation_us_gal(self):
        for plan in self:
            plan.irrigation_us_gal = plan.irrigation_m3 * 264.172052

    @api.depends('expected_yield_per_ha')
    def _compute_expected_yield_per_acre(self):
        for plan in self:
            plan.expected_yield_per_acre = plan.expected_yield_per_ha / 2.4710538

    def _inverse_expected_yield_per_acre(self):
        for plan in self:
            plan.expected_yield_per_ha = plan.expected_yield_per_acre * 2.4710538

    @api.depends('cost_per_ha')
    def _compute_cost_per_acre(self):
        for plan in self:
            plan.cost_per_acre = plan.cost_per_ha / 2.4710538

    @api.depends('yield_per_ha')
    def _compute_yield_per_acre(self):
        for plan in self:
            plan.yield_per_acre = plan.yield_per_ha / 2.4710538

    @api.depends('rain_since_sowing_mm')
    def _compute_rain_since_sowing_in(self):
        for plan in self:
            plan.rain_since_sowing_in = plan.rain_since_sowing_mm / 25.4

    @api.depends('gdd_accumulated')
    def _compute_gdd_accumulated_f(self):
        for plan in self:
            plan.gdd_accumulated_f = plan.gdd_accumulated * 9 / 5

    @api.depends('crop_id', 'variety_id')
    def _compute_growing_days(self):
        for plan in self:
            plan.growing_days = plan.variety_id.growing_days or plan.crop_id.growing_days

    @api.depends('sowing_date', 'actual_sowing_date', 'growing_days')
    def _compute_expected_harvest_date(self):
        for plan in self:
            start = plan.actual_sowing_date or plan.sowing_date
            plan.expected_harvest_date = start + timedelta(days=plan.growing_days) if start else False

    @api.depends('crop_id', 'variety_id')
    def _compute_expected_yield(self):
        for plan in self:
            plan.expected_yield_per_ha = plan.variety_id.expected_yield_per_ha or plan.crop_id.expected_yield_per_ha

    @api.depends('expected_yield_per_ha', 'area_ha')
    def _compute_expected_yield_total(self):
        for plan in self:
            plan.expected_yield = plan.expected_yield_per_ha * plan.area_ha

    def _compute_counts(self):
        for plan in self:
            plan.field_activity_count = len(plan.field_activity_ids)
            plan.harvest_count = len(plan.harvest_ids)
            plan.scouting_count = len(plan.scouting_ids)
            plan.open_scouting_count = len(plan.scouting_ids.filtered(lambda s: s.state in ('draft', 'reviewed')))
            plan.sale_order_count = len(plan.sale_line_ids.order_id)
            plan.purchase_count = self.env['purchase.order'].search_count([('mdv_crop_plan_id', '=', plan.id)])

    @api.depends('cost_line_ids.amount', 'cost_line_ids.cost_type')
    def _compute_costs(self):
        for plan in self:
            totals = defaultdict(float)
            for line in plan.cost_line_ids:
                totals[line.cost_type] += line.amount
            plan.material_cost = totals['material']
            plan.labour_cost = totals['labour']
            plan.machine_cost = totals['machine']
            plan.overhead_cost = totals['overhead'] + totals['feed'] + totals['vet']
            plan.direct_cost = sum(totals.values())

    @api.depends('budget_line_ids.amount')
    def _compute_budget(self):
        for plan in self:
            plan.budget_total = sum(plan.budget_line_ids.mapped('amount'))

    @api.depends('harvest_ids.quantity', 'harvest_ids.state', 'area_ha', 'expected_yield')
    def _compute_harvest(self):
        for plan in self:
            qty = sum(plan.harvest_ids.filtered(lambda h: h.state == 'done').mapped('quantity'))
            plan.harvested_qty = qty
            plan.yield_per_ha = qty / plan.area_ha if plan.area_ha else 0.0
            plan.yield_gap_pct = (qty / plan.expected_yield * 100.0) if plan.expected_yield else 0.0

    @api.depends('sale_line_ids.price_subtotal', 'sale_line_ids.state')
    def _compute_revenue(self):
        for plan in self:
            revenue = 0.0
            for line in plan.sale_line_ids.filtered(lambda sl: sl.state == 'sale'):
                revenue += line.currency_id._convert(line.price_subtotal, plan.currency_id, plan.company_id,
                                                     line.order_id.date_order or fields.Date.today())
            plan.revenue = revenue

    def _compute_other_cost(self):
        AnalyticLine = self.env['account.analytic.line'].sudo()
        for plan in self:
            other = 0.0
            if plan.analytic_account_id:
                lines = AnalyticLine.search([('account_id', '=', plan.analytic_account_id.id),
                                             ('mdv_agri_cost_line_id', '=', False)])
                other = -sum(lines.mapped('amount'))
            plan.other_cost = other
            plan.total_cost = plan.direct_cost + other
            plan.budget_variance = plan.budget_total - plan.total_cost
            plan.budget_used_pct = plan.total_cost / plan.budget_total * 100.0 if plan.budget_total else 0.0
            plan.cost_per_ha = plan.total_cost / plan.area_ha if plan.area_ha else 0.0
            plan.cost_per_unit = plan.total_cost / plan.harvested_qty if plan.harvested_qty else 0.0
            plan.margin = plan.revenue - plan.total_cost

    def _compute_agronomy(self):
        today = fields.Date.context_today(self)
        Weather = self.env['mdv.agri.weather.log']
        for plan in self:
            start = plan.actual_sowing_date or (plan.sowing_date if plan.state in ('growing', 'harvested', 'closed')
                                                else False)
            end = min(today, plan.harvest_end_date or today)
            plan.days_since_sowing = (today - start).days if start and start <= today else 0
            plan.progress_pct = min(100.0, plan.days_since_sowing / plan.growing_days * 100.0) \
                if plan.growing_days and plan.days_since_sowing else 0.0
            gdd = rain = 0.0
            if start and start <= end:
                base = plan.crop_id.base_temperature_c
                logs = Weather.search([('farm_id', '=', plan.farm_id.id), ('date', '>=', start), ('date', '<=', end),
                                       ('is_forecast', '=', False)])
                for log in logs:
                    gdd += log._gdd(base)
                    rain += log.precipitation_mm
            plan.gdd_accumulated = gdd
            plan.rain_since_sowing_mm = rain
            plan.irrigation_m3 = sum(plan.field_activity_ids.filtered(
                lambda a: a.state == 'done' and a.activity_type == 'irrigation').mapped('water_m3'))

    # ------------------------------------------------------------------ constraints
    @api.constrains('field_id', 'sowing_date', 'expected_harvest_date', 'state')
    def _check_field_overlap(self):
        """Draft plans may overlap (they are scenarios); planned and running ones may not."""
        active_states = ('confirmed', 'growing')
        for plan in self.filtered(lambda p: p.state in active_states):
            end = plan.expected_harvest_date or plan.sowing_date
            others = self.search([
                ('id', '!=', plan.id), ('field_id', '=', plan.field_id.id), ('state', 'in', active_states),
                ('sowing_date', '<=', end), ('expected_harvest_date', '>=', plan.sowing_date),
            ])
            if others:
                raise ValidationError(_('Field %(field)s already has crop plan %(other)s in that period.',
                                        field=plan.field_id.display_name, other=others[0].name))

    @api.constrains('area_ha', 'field_id')
    def _check_area(self):
        for plan in self:
            if plan.area_ha < 0:
                raise ValidationError(_('The planted area cannot be negative.'))
            if plan.field_id.area_ha and float_compare(plan.area_ha, plan.field_id.area_ha, precision_digits=2) > 0:
                raise ValidationError(_('The planted area (%(plan)s ha) is larger than field %(field)s (%(area)s ha).',
                                        plan=plan.area_ha, field=plan.field_id.name, area=plan.field_id.area_ha))

    # ------------------------------------------------------------------ workflow
    def action_confirm(self):
        for plan in self:
            if plan.state != 'draft':
                raise UserError(_('Only draft crop plans can be confirmed.'))
            plan.state = 'confirmed'
            plan._ensure_analytic_account()
            if not plan.field_activity_ids:
                plan._generate_activities()
            if not plan.budget_line_ids:
                plan._generate_budget()
        return True

    def action_start(self):
        for plan in self.filtered(lambda p: p.state == 'confirmed'):
            plan.state = 'growing'
            if not plan.actual_sowing_date:
                plan.actual_sowing_date = fields.Date.context_today(plan)
        return True

    def action_mark_harvested(self):
        for plan in self:
            if plan.state not in ('confirmed', 'growing'):
                raise UserError(_('Only planned or growing crops can be marked as harvested.'))
            if plan.harvest_ids.filtered(lambda h: h.state == 'draft'):
                raise UserError(_('Validate or cancel the draft harvests of %s first.', plan.name))
            plan.write({'state': 'harvested',
                        'harvest_end_date': plan.harvest_end_date or fields.Date.context_today(plan)})
        return True

    def action_close(self):
        for plan in self:
            if plan.state != 'harvested':
                raise UserError(_('Only harvested crop plans can be closed.'))
            open_acts = plan.field_activity_ids.filtered(lambda a: a.state == 'planned')
            open_acts.write({'state': 'cancelled'})
            plan.state = 'closed'
        return True

    def action_cancel(self):
        for plan in self:
            if plan.field_activity_ids.filtered(lambda a: a.state == 'done') or \
                    plan.harvest_ids.filtered(lambda h: h.state == 'done'):
                raise UserError(_('%s has done activities or harvests and cannot be cancelled.', plan.name))
            plan.field_activity_ids.write({'state': 'cancelled'})
            plan.state = 'cancelled'
        return True

    def action_draft(self):
        for plan in self.filtered(lambda p: p.state in ('cancelled', 'confirmed')):
            if plan.field_activity_ids.filtered(lambda a: a.state == 'done'):
                raise UserError(_('%s has done activities and cannot go back to draft.', plan.name))
            plan.field_activity_ids.filtered(lambda a: a.state != 'done').unlink()
            plan.state = 'draft'
        return True

    def _ensure_analytic_account(self):
        for plan in self:
            if plan.analytic_account_id or not plan.company_id.mdv_agri_analytic:
                continue
            project_plan, _other = self.env['account.analytic.plan'].sudo()._get_all_plans()
            plan.analytic_account_id = self.env['account.analytic.account'].sudo().create({
                'name': '%s - %s - %s' % (plan.crop_id.name, plan.field_id.name, plan.season_id.name),
                'code': plan.name,
                'plan_id': project_plan.id,
                'company_id': plan.company_id.id,
            })

    def _generate_activities(self):
        Activity = self.env['mdv.agri.activity']
        company = self.company_id
        for plan in self:
            vals_list = []
            for tmpl in plan.crop_id.template_line_ids:
                materials = []
                if tmpl.product_id and tmpl.qty_per_ha:
                    materials.append((0, 0, {'product_id': tmpl.product_id.id,
                                             'quantity': round(tmpl.qty_per_ha * plan.area_ha, 3),
                                             'uom_id': tmpl.product_id.uom_id.id}))
                vals_list.append({
                    'name': tmpl.name,
                    'plan_id': plan.id,
                    'activity_type': tmpl.activity_type,
                    'date_planned': plan.sowing_date + timedelta(days=tmpl.day_offset),
                    'planned_labour_hours': tmpl.labour_hours_per_ha * plan.area_ha,
                    'planned_machine_hours': tmpl.machine_hours_per_ha * plan.area_ha,
                    'material_line_ids': materials,
                })
            Activity.create(vals_list)
        return True

    def _generate_budget(self):
        Budget = self.env['mdv.agri.budget.line']
        for plan in self:
            company = plan.company_id
            vals_list = []
            labour_h = machine_h = 0.0
            for tmpl in plan.crop_id.template_line_ids:
                if tmpl.product_id and tmpl.qty_per_ha:
                    vals_list.append({'plan_id': plan.id, 'cost_type': 'material', 'name': tmpl.product_id.display_name,
                                      'product_id': tmpl.product_id.id, 'quantity': tmpl.qty_per_ha * plan.area_ha,
                                      'unit_cost': tmpl.product_id.standard_price})
                labour_h += tmpl.labour_hours_per_ha * plan.area_ha
                machine_h += tmpl.machine_hours_per_ha * plan.area_ha
            if labour_h:
                vals_list.append({'plan_id': plan.id, 'cost_type': 'labour', 'name': _('Field labour'),
                                  'quantity': labour_h, 'unit_cost': company.mdv_agri_labour_rate})
            if machine_h:
                vals_list.append({'plan_id': plan.id, 'cost_type': 'machine', 'name': _('Machinery'),
                                  'quantity': machine_h, 'unit_cost': company.mdv_agri_machine_rate})
            if plan.field_id.tenure == 'leased' and plan.field_id.lease_cost_per_season:
                vals_list.append({'plan_id': plan.id, 'cost_type': 'overhead', 'name': _('Land lease'),
                                  'quantity': 1, 'unit_cost': plan.field_id.lease_cost_per_season})
            Budget.create(vals_list)
        return True

    def action_regenerate_budget(self):
        self.budget_line_ids.unlink()
        self._generate_budget()

    def action_add_lease_cost(self):
        """Book the season's land lease as an overhead cost."""
        for plan in self:
            if plan.field_id.tenure != 'leased' or not plan.field_id.lease_cost_per_season:
                raise UserError(_('Field %s has no lease cost.', plan.field_id.name))
            lease_label = _('Land lease')
            if plan.cost_line_ids.filtered(lambda c: c.cost_type == 'overhead' and c.name == lease_label):
                continue
            self.env['mdv.agri.cost.line'].create({
                'name': _('Land lease'), 'cost_type': 'overhead', 'plan_id': plan.id,
                'farm_id': plan.farm_id.id, 'field_id': plan.field_id.id, 'company_id': plan.company_id.id,
                'quantity': 1, 'unit_cost': plan.field_id.lease_cost_per_season,
                'amount': plan.field_id.lease_cost_per_season,
            })

    # ------------------------------------------------------------------ purchase
    def _material_shortage(self):
        """Materials still needed by planned activities that the farm location does not hold."""
        self.ensure_one()
        needed = defaultdict(float)
        for line in self.field_activity_ids.filtered(lambda a: a.state == 'planned').material_line_ids:
            needed[line.product_id] += line.uom_id._compute_quantity(line.quantity, line.product_id.uom_id)
        location = self.farm_id._get_consumption_location()
        Quant = self.env['stock.quant'].sudo()
        shortage = {}
        for product, qty in needed.items():
            if not product.is_storable:
                continue
            available = Quant._get_available_quantity(product, location)
            if float_compare(qty, available, precision_rounding=product.uom_id.rounding) > 0:
                shortage[product] = qty - available
        return shortage

    def action_purchase_materials(self):
        """Create draft purchase orders (one per vendor) for the missing materials."""
        self.ensure_one()
        shortage = self._material_shortage()
        if not shortage:
            raise UserError(_('The farm location already holds every material the planned activities need.'))
        no_vendor = [p.display_name for p in shortage if not p.seller_ids]
        if no_vendor:
            raise UserError(_('Set a vendor on these products first:\n%s', '\n'.join(no_vendor)))
        by_vendor = defaultdict(list)
        for product, qty in shortage.items():
            by_vendor[product.seller_ids[0].partner_id].append((product, qty))
        orders = self.env['purchase.order']
        picking_type = self.farm_id.warehouse_id.in_type_id
        for vendor, lines in by_vendor.items():
            orders |= self.env['purchase.order'].create({
                'partner_id': vendor.id,
                'company_id': self.company_id.id,
                'origin': self.name,
                'mdv_crop_plan_id': self.id,
                'picking_type_id': picking_type.id if picking_type else False,
                'order_line': [(0, 0, {'product_id': p.id, 'product_qty': q}) for p, q in lines],
            })
        return self._open_records(orders, _('Purchase Orders'))

    # ------------------------------------------------------------------ navigation
    def _open_records(self, records, title):
        action = {'type': 'ir.actions.act_window', 'name': title, 'res_model': records._name}
        if len(records) == 1:
            action.update({'view_mode': 'form', 'res_id': records.id})
        else:
            action.update({'view_mode': 'list,form', 'domain': [('id', 'in', records.ids)]})
        return action

    def _action_related(self, xmlid):
        action = self.env['ir.actions.act_window']._for_xml_id(xmlid)
        action['domain'] = [('plan_id', '=', self.id)]
        action['context'] = {'default_plan_id': self.id}
        return action

    def action_view_activities(self):
        return self._action_related('mdv_agriculture_suite.action_agri_activity')

    def action_view_harvests(self):
        return self._action_related('mdv_agriculture_suite.action_agri_harvest')

    def action_view_scouting(self):
        return self._action_related('mdv_agriculture_suite.action_agri_scouting')

    def action_view_costs(self):
        return self._action_related('mdv_agriculture_suite.action_agri_cost_line')

    def action_view_sale_orders(self):
        return self._open_records(self.sale_line_ids.order_id, _('Sales Orders'))

    def action_view_purchases(self):
        return self._open_records(self.env['purchase.order'].search([('mdv_crop_plan_id', '=', self.id)]),
                                  _('Purchase Orders'))

    def action_print_cost_sheet(self):
        return self.env.ref('mdv_agriculture_suite.action_report_job_cost_sheet').report_action(self)

    def _cost_sheet_rows(self):
        """Budget vs actual per cost type for the job cost sheet."""
        self.ensure_one()
        labels = dict(self.env['mdv.agri.cost.line']._fields['cost_type'].selection)
        budget = defaultdict(float)
        actual = defaultdict(float)
        for line in self.budget_line_ids:
            budget[line.cost_type] += line.amount
        for line in self.cost_line_ids:
            actual[line.cost_type] += line.amount
        rows = []
        for key in labels:
            if budget[key] or actual[key]:
                rows.append({'label': labels[key], 'budget': budget[key], 'actual': actual[key],
                             'variance': budget[key] - actual[key]})
        if self.other_cost:
            rows.append({'label': _('Bills and expenses'), 'budget': 0.0, 'actual': self.other_cost,
                         'variance': -self.other_cost})
        return rows

    @api.model
    def _cron_start_due_plans(self):
        """Planned crops whose sowing activity is done move to Growing automatically."""
        plans = self.search([('state', '=', 'confirmed')])
        for plan in plans:
            if plan.field_activity_ids.filtered(lambda a: a.state == 'done' and a.activity_type == 'sowing'):
                plan.action_start()
