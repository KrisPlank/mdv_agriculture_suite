from odoo import _, api, fields, models
from odoo.exceptions import UserError

from .crop import ACTIVITY_TYPES


class AgriActivity(models.Model):
    _name = 'mdv.agri.activity'
    _description = 'Field Activity'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'mdv.agri.stock.mixin']
    _order = 'date_planned, id'
    _check_company_auto = True

    name = fields.Char(required=True, tracking=True)
    activity_type = fields.Selection(ACTIVITY_TYPES, required=True, default='other', tracking=True)
    state = fields.Selection([('planned', 'Planned'), ('done', 'Done'), ('cancelled', 'Cancelled')],
                             default='planned', required=True, tracking=True, copy=False)
    plan_id = fields.Many2one('mdv.agri.crop.plan', required=True, ondelete='cascade', index=True,
                              check_company=True)
    field_id = fields.Many2one(related='plan_id.field_id', store=True)
    farm_id = fields.Many2one(related='plan_id.farm_id', store=True)
    crop_id = fields.Many2one(related='plan_id.crop_id', store=True)
    season_id = fields.Many2one(related='plan_id.season_id', store=True)
    company_id = fields.Many2one(related='plan_id.company_id', store=True)
    currency_id = fields.Many2one(related='company_id.currency_id')
    user_id = fields.Many2one('res.users', 'Responsible', default=lambda self: self.env.user)
    date_planned = fields.Date('Planned Date', required=True, default=fields.Date.context_today)
    date_done = fields.Date('Done On', copy=False)
    is_overdue = fields.Boolean(compute='_compute_is_overdue', search='_search_is_overdue')
    planned_labour_hours = fields.Float()
    planned_machine_hours = fields.Float()
    water_m3 = fields.Float('Water (m3)', help='Irrigation water applied.')
    scouting_id = fields.Many2one('mdv.agri.scouting', 'From Scouting', copy=False)
    weather_log_id = fields.Many2one('mdv.agri.weather.log', compute='_compute_weather_log')
    material_line_ids = fields.One2many('mdv.agri.activity.material', 'activity_id', string='Materials', copy=True)
    labour_line_ids = fields.One2many('mdv.agri.activity.labour', 'activity_id', string='Labour')
    machine_line_ids = fields.One2many('mdv.agri.activity.machine', 'activity_id', string='Machinery')
    move_ids = fields.Many2many('stock.move', string='Stock Moves', copy=False, readonly=True)
    cost_line_ids = fields.One2many('mdv.agri.cost.line', 'activity_id', string='Costs')
    total_cost = fields.Monetary(compute='_compute_total_cost', currency_field='currency_id')
    notes = fields.Html()
    color = fields.Integer(compute='_compute_color')

    def _compute_is_overdue(self):
        today = fields.Date.context_today(self)
        for act in self:
            act.is_overdue = act.state == 'planned' and act.date_planned < today

    def _search_is_overdue(self, operator, value):
        if operator not in ('=', '!=') or not isinstance(value, bool):
            raise UserError(_('Unsupported search on overdue.'))
        domain = [('state', '=', 'planned'), ('date_planned', '<', fields.Date.context_today(self))]
        positive = (operator == '=') == value
        return domain if positive else ['!', '&'] + domain

    @api.depends('activity_type')
    def _compute_color(self):
        colors = {'land_prep': 3, 'sowing': 10, 'irrigation': 4, 'fertilizer': 2, 'spraying': 1,
                  'weeding': 5, 'harvest': 7, 'other': 0}
        for act in self:
            act.color = colors.get(act.activity_type, 0)

    @api.depends('cost_line_ids.amount')
    def _compute_total_cost(self):
        for act in self:
            act.total_cost = sum(act.cost_line_ids.mapped('amount'))

    def _compute_weather_log(self):
        Weather = self.env['mdv.agri.weather.log']
        for act in self:
            act.weather_log_id = Weather.search(
                [('farm_id', '=', act.farm_id.id), ('date', '=', act.date_done or act.date_planned)], limit=1)

    def action_done(self):
        for act in self:
            if act.state != 'planned':
                raise UserError(_('Only planned activities can be marked as done.'))
            if act.plan_id.state not in ('confirmed', 'growing'):
                raise UserError(_('Confirm crop plan %s before recording activities.', act.plan_id.name))
            act._do_done()
        return True

    def _do_done(self):
        self.ensure_one()
        date_done = self.date_done or fields.Date.context_today(self)
        company = self.company_id
        location = self.farm_id._get_consumption_location()
        lines = [(ml.product_id, ml.quantity, ml.uom_id) for ml in self.material_line_ids]
        moves = self._agri_consume(lines, location, company, '%s / %s' % (self.plan_id.name, self.name))
        cost_vals = []
        base = {'activity_id': self.id, 'plan_id': self.plan_id.id, 'farm_id': self.farm_id.id,
                'field_id': self.field_id.id, 'company_id': company.id, 'date': date_done}
        for ml in self.material_line_ids:
            unit_cost = ml.product_id.standard_price
            qty = ml.uom_id._compute_quantity(ml.quantity, ml.product_id.uom_id)
            ml.unit_cost = unit_cost
            cost_vals.append(dict(base, name=ml.product_id.display_name, cost_type='material',
                                  product_id=ml.product_id.id, quantity=qty, unit_label=ml.product_id.uom_id.name,
                                  unit_cost=unit_cost, amount=qty * unit_cost))
        for ll in self.labour_line_ids:
            cost_vals.append(dict(base, name=ll.employee_id.name, cost_type='labour', employee_id=ll.employee_id.id,
                                  quantity=ll.hours, unit_label=_('h'), unit_cost=ll.hourly_cost,
                                  amount=ll.hours * ll.hourly_cost))
        for mc in self.machine_line_ids:
            cost_vals.append(dict(base, name=mc.equipment_id.name, cost_type='machine', equipment_id=mc.equipment_id.id,
                                  quantity=mc.hours, unit_label=_('h'), unit_cost=mc.hourly_rate,
                                  amount=mc.hours * mc.hourly_rate))
        self.env['mdv.agri.cost.line'].create(cost_vals)
        self.write({'state': 'done', 'date_done': date_done})
        self.sudo().move_ids = [(6, 0, moves.ids)]
        plan = self.plan_id
        if self.activity_type in ('sowing', 'land_prep', 'irrigation', 'fertilizer', 'spraying', 'weeding') \
                and plan.state == 'confirmed':
            plan.state = 'growing'
        if self.activity_type == 'sowing' and not plan.actual_sowing_date:
            plan.actual_sowing_date = date_done
        if self.scouting_id and self.activity_type == 'spraying' and self.scouting_id.state != 'closed':
            self.scouting_id.state = 'treated'
        self.machine_line_ids.equipment_id._mdv_check_service_due()

    def action_reset(self):
        """Undo a done activity: return the consumed stock and remove its cost entries."""
        for act in self.filtered(lambda a: a.state == 'done'):
            act._agri_reverse(act.sudo().move_ids, _('Undo %s', act.name))
            act.cost_line_ids.unlink()
            act.write({'state': 'planned', 'date_done': False})
            act.sudo().move_ids = [(5, 0, 0)]
        return True

    def action_cancel(self):
        if self.filtered(lambda a: a.state == 'done'):
            raise UserError(_('Reset a done activity before cancelling it.'))
        self.write({'state': 'cancelled'})
        return True

    def action_view_moves(self):
        return {'type': 'ir.actions.act_window', 'name': _('Stock Moves'), 'res_model': 'stock.move',
                'view_mode': 'list,form', 'domain': [('id', 'in', self.move_ids.ids)]}


class AgriActivityMaterial(models.Model):
    _name = 'mdv.agri.activity.material'
    _description = 'Activity Material'

    activity_id = fields.Many2one('mdv.agri.activity', required=True, ondelete='cascade', index=True)
    product_id = fields.Many2one('product.product', required=True, domain=[('type', '=', 'consu')])
    quantity = fields.Float(required=True, default=1.0, digits='Product Unit')
    uom_id = fields.Many2one('uom.uom', 'Unit', compute='_compute_uom_id', store=True, readonly=False)
    unit_cost = fields.Float(digits='Product Price', readonly=True)
    rate_per_ha = fields.Float('Rate per ha', compute='_compute_rate', digits=(16, 3))

    @api.depends('product_id')
    def _compute_uom_id(self):
        for line in self:
            line.uom_id = line.product_id.uom_id

    @api.depends('quantity', 'activity_id.plan_id.area_ha')
    def _compute_rate(self):
        for line in self:
            area = line.activity_id.plan_id.area_ha
            line.rate_per_ha = line.quantity / area if area else 0.0


class AgriActivityLabour(models.Model):
    _name = 'mdv.agri.activity.labour'
    _description = 'Activity Labour'

    activity_id = fields.Many2one('mdv.agri.activity', required=True, ondelete='cascade', index=True)
    employee_id = fields.Many2one('hr.employee', required=True)
    hours = fields.Float(required=True, default=1.0)
    hourly_cost = fields.Float(compute='_compute_hourly_cost', store=True, readonly=False, digits='Product Price')
    amount = fields.Float(compute='_compute_amount', digits='Product Price')

    @api.depends('employee_id')
    def _compute_hourly_cost(self):
        for line in self:
            line.hourly_cost = line.employee_id.sudo().hourly_cost or \
                (line.activity_id.company_id or self.env.company).mdv_agri_labour_rate

    @api.depends('hours', 'hourly_cost')
    def _compute_amount(self):
        for line in self:
            line.amount = line.hours * line.hourly_cost


class AgriActivityMachine(models.Model):
    _name = 'mdv.agri.activity.machine'
    _description = 'Activity Machinery'

    activity_id = fields.Many2one('mdv.agri.activity', required=True, ondelete='cascade', index=True)
    equipment_id = fields.Many2one('maintenance.equipment', required=True)
    operator_id = fields.Many2one('hr.employee')
    hours = fields.Float(required=True, default=1.0)
    hourly_rate = fields.Float(compute='_compute_hourly_rate', store=True, readonly=False, digits='Product Price')
    amount = fields.Float(compute='_compute_amount', digits='Product Price')
    state = fields.Selection(related='activity_id.state', store=True)

    @api.depends('equipment_id')
    def _compute_hourly_rate(self):
        for line in self:
            line.hourly_rate = line.equipment_id.mdv_agri_hourly_rate or \
                (line.activity_id.company_id or self.env.company).mdv_agri_machine_rate

    @api.depends('hours', 'hourly_rate')
    def _compute_amount(self):
        for line in self:
            line.amount = line.hours * line.hourly_rate
